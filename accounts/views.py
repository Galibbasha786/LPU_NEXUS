# accounts/views.py
import os
import re
import uuid
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
from django.core.files.storage import default_storage
from django.views.decorators.http import require_http_methods
from crisis.services import crisis_stats
from .mongo_auth import (
    create_student, create_staff, authenticate_user,
    list_staff, list_students, get_student_profile, find_user_by_identifier,
    get_user_by_id, set_user_password, verify_recovery_answer,
    verify_current_password, update_account_details, delete_account,
)
from .id_card_verification import (
    IdCardReadError, OcrUnavailableError, verify_student_id_card,
)
from .session import (
    login_session, logout_session, get_current_user,
    login_required_mongo, role_required,
)
from core.mongo import users


ALLOWED_ID_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.pdf'}
MAX_ID_SIZE = 5 * 1024 * 1024   # 5 MB
RECOVERY_QUESTIONS = {
    'pet': "What is your pet's name?",
    'movie': 'What is your favorite movie?',
    'inspiration': 'Who is your inspiration?',
}


def home_view(request):
    return render(request, 'home.html')


# ============================================================
#  STUDENT SELF-REGISTRATION
# ============================================================
@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.session.get('lpu_user_id'):
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        full_name = request.POST.get('full_name', '').strip()
        reg_no = request.POST.get('registration_number', '').strip()
        department = request.POST.get('department', '').strip()
        year = request.POST.get('year', '').strip()
        recovery_question = request.POST.get('recovery_question', '').strip()
        recovery_answer = request.POST.get('recovery_answer', '')
        id_card = request.FILES.get('id_card')

        errors = []
        if not all([email, password, full_name, reg_no]):
            errors.append("Please fill all required fields.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if recovery_question not in RECOVERY_QUESTIONS:
            errors.append("Please choose a password recovery question.")
        if not id_card:
            errors.append("LPU ID card image is required.")

        id_card_path = ''
        if id_card:
            ext = os.path.splitext(id_card.name)[1].lower()
            if ext not in ALLOWED_ID_EXT:
                errors.append("ID card must be JPG, PNG, WEBP, or PDF.")
            elif id_card.size > MAX_ID_SIZE:
                errors.append("ID card must be under 5 MB.")

        if not errors:
            try:
                matches = verify_student_id_card(id_card, full_name, reg_no)
                if not matches['name_matches']:
                    errors.append("The name on the ID card does not match the name entered.")
                if not matches['registration_number_matches']:
                    errors.append("The UID on the ID card does not match the registration number entered.")
            except OcrUnavailableError:
                errors.append("ID verification is temporarily unavailable. Contact the administrator.")
            except IdCardReadError:
                errors.append("The ID card could not be read. Upload a clear image or PDF and try again.")

        if not errors and id_card:
            fname = f"id_cards/{uuid.uuid4().hex}{ext}"
            id_card_path = default_storage.save(fname, id_card)

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'accounts/register.html', {
                'form_data': request.POST,
            })

        user, err = create_student(
            email=email, password=password, full_name=full_name,
            registration_number=reg_no, department=department,
            year=year, id_card_path=id_card_path,
            recovery_question=RECOVERY_QUESTIONS[recovery_question],
            recovery_answer=recovery_answer,
        )
        if err:
            # clean up orphaned upload
            if id_card_path:
                try:
                    default_storage.delete(id_card_path)
                except Exception:
                    pass
            messages.error(request, err)
            return render(request, 'accounts/register.html', {
                'form_data': request.POST,
            })

        login_session(request, user)
        messages.success(request, f"Welcome, {full_name}!")
        return redirect('accounts:dashboard')

    return render(request, 'accounts/register.html')


# ============================================================
#  LOGIN / LOGOUT
# ============================================================
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.session.get('lpu_user_id'):
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        password = request.POST.get('password', '')
        user = authenticate_user(identifier, password)
        if user:
            login_session(request, user)
            messages.success(request, f"Welcome back, {user.get('full_name')}!")
            return redirect('accounts:dashboard')
        messages.error(request, "Invalid UID, email, or password.")

    return render(request, 'accounts/login.html')


@require_http_methods(["GET", "POST"])
def forgot_password_view(request):
    stage = 'identify'
    user = None
    if request.method == 'GET':
        request.session.pop('password_reset_user_id', None)
        request.session.pop('password_reset_verified', None)

    if request.method == 'POST':
        stage = request.POST.get('stage', 'identify')

        if stage == 'identify':
            request.session.pop('password_reset_user_id', None)
            request.session.pop('password_reset_verified', None)
            identifier = request.POST.get('identifier', '').strip()
            user = find_user_by_identifier(identifier)
            if not user or not user.get('recovery_answer_hash') or not user.get('recovery_question'):
                messages.error(request, "No recovery question is available for that account.")
            elif not user.get('active', True):
                messages.error(request, "This account is inactive. Please contact an administrator.")
            else:
                request.session['password_reset_user_id'] = str(user['_id'])
                stage = 'answer'

        elif stage == 'answer':
            user_id = request.session.get('password_reset_user_id')
            user = get_user_by_id(user_id) if user_id else None
            if user and user.get('active', True) and verify_recovery_answer(
                user, request.POST.get('recovery_answer', '')
            ):
                request.session['password_reset_verified'] = True
                stage = 'password'
            else:
                request.session.pop('password_reset_user_id', None)
                request.session.pop('password_reset_verified', None)
                messages.error(request, "The recovery answer could not be verified. Start again.")

        elif stage == 'password':
            user_id = request.session.get('password_reset_user_id')
            user = get_user_by_id(user_id) if user_id else None
            password = request.POST.get('password', '')
            confirm = request.POST.get('confirm_password', '')
            if not request.session.get('password_reset_verified') or not user or not user.get('active', True):
                request.session.pop('password_reset_user_id', None)
                request.session.pop('password_reset_verified', None)
                stage = 'identify'
                messages.error(request, "Verify your recovery answer before changing the password.")
            elif len(password) < 6:
                stage = 'password'
                messages.error(request, "Password must be at least 6 characters.")
            elif password != confirm:
                stage = 'password'
                messages.error(request, "Passwords do not match.")
            else:
                set_user_password(user_id, password)
                request.session.pop('password_reset_user_id', None)
                request.session.pop('password_reset_verified', None)
                messages.success(request, "Your password has been changed. Please sign in.")
                return redirect('accounts:login')

    if stage in ('answer', 'password') and user is None:
        user_id = request.session.get('password_reset_user_id')
        user = get_user_by_id(user_id) if user_id else None
    if not user and stage != 'identify':
        stage = 'identify'
    return render(request, 'accounts/forgot_password.html', {
        'stage': stage,
        'recovery_question': user.get('recovery_question', '') if user else '',
        'identifier': request.POST.get('identifier', ''),
    })


def logout_view(request):
    logout_session(request)
    messages.info(request, "You've been logged out.")
    return redirect('accounts:login')


@login_required_mongo
@role_required('student', 'staff')
@require_http_methods(["GET", "POST"])
def profile_view(request):
    user_id = request.session.get('lpu_user_id')
    user = get_user_by_id(user_id)
    if not user:
        logout_session(request)
        messages.warning(request, "Please sign in again to manage your profile.")
        return redirect('accounts:login')
    profile = get_student_profile(user_id) if user.get('role') == 'student' else {}
    action = request.POST.get('action', '')

    if request.method == 'POST' and action == 'update_details':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        department = request.POST.get('department', '').strip()
        year = request.POST.get('year', '').strip()
        designation = request.POST.get('designation', '').strip()
        phone = request.POST.get('phone', '').strip()
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Enter a valid email address.")
        else:
            if not full_name:
                messages.error(request, "Full name is required.")
            else:
                updated, error = update_account_details(
                    user_id, full_name, email, department, year, designation, phone,
                )
                if error:
                    messages.error(request, error)
                else:
                    request.session['lpu_user_name'] = full_name
                    messages.success(request, "Your profile details have been updated.")
                    return redirect('accounts:profile')

    elif request.method == 'POST' and action == 'change_password':
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        if not verify_current_password(user, current_password):
            messages.error(request, "Your current password is incorrect.")
        elif len(new_password) < 6:
            messages.error(request, "New password must be at least 6 characters.")
        elif new_password != confirm_password:
            messages.error(request, "New passwords do not match.")
        else:
            set_user_password(user_id, new_password)
            messages.success(request, "Your password has been changed.")
            return redirect('accounts:profile')

    elif request.method == 'POST' and action == 'delete_account':
        if request.POST.get('confirmation', '').strip() != 'DELETE':
            messages.error(request, "Type DELETE to confirm account deletion.")
        else:
            deleted_user = delete_account(user_id, request.POST.get('delete_password', ''))
            if not deleted_user:
                messages.error(request, "The password is incorrect; your account was not deleted.")
            else:
                id_card_path = profile.get('id_card_path') if profile else ''
                if id_card_path:
                    try:
                        default_storage.delete(id_card_path)
                    except OSError:
                        pass
                logout_session(request)
                messages.success(request, "Your account has been deleted.")
                return redirect('accounts:home')

    return render(request, 'accounts/profile.html', {
        'user': user,
        'profile': profile,
        'form_data': request.POST if action == 'update_details' else {},
    })


# ============================================================
#  DASHBOARD ROUTER
# ============================================================
@login_required_mongo
def dashboard_view(request):
    role = request.session.get('lpu_user_role', 'student')
    if role == 'admin':
        return redirect('accounts:admin_dashboard')
    elif role == 'staff':
        return redirect('accounts:staff_dashboard')
    return redirect('accounts:student_dashboard')


# ============================================================
#  STUDENT DASHBOARD
# ============================================================
@login_required_mongo
@role_required('student')
def student_dashboard(request):
    user = get_current_user(request)
    profile = get_student_profile(request.session.get('lpu_user_id'))
    from core.utils import serialize_doc
    profile = serialize_doc(profile)

    stats = {
        'my_reports': 0,
        'affected_confirmations': 0,
        'my_ideas': 0,
        'open_emergencies': 0,
    }
    return render(request, 'accounts/dashboard_student.html', {
        'user': user, 'profile': profile, 'stats': stats,
    })


# ============================================================
#  STAFF DASHBOARD
# ============================================================
@login_required_mongo
@role_required('staff', 'admin')
def staff_dashboard(request):
    user = get_current_user(request)
    stats = {
        'assigned_to_me': 0,
        'in_progress': 0,
        'resolved_today': 0,
        'pending_ack': 0,
    }
    return render(request, 'accounts/dashboard_staff.html', {
        'user': user, 'stats': stats,
    })


# ============================================================
#  ADMIN DASHBOARD + STAFF MANAGEMENT
# ============================================================
@login_required_mongo
@role_required('admin')
def admin_dashboard(request):
    user = get_current_user(request)
    staff_list = list_staff()
    student_count = users().count_documents({'role': 'student'})

    from crisis.services import crisis_stats
    crisis_st = crisis_stats()

    stats = {
        'total_problems': 0,
        'open_problems': 0,
        'total_ideas': 0,
        'active_emergencies': crisis_st.get('total_open', 0),
        'total_users': users().count_documents({}),
        'total_students': student_count,
        'total_staff': len(staff_list),
        'crisis_mode': crisis_st.get('crisis_mode', False),   # ← ADD
    }
    from core.utils import serialize_list
    return render(request, 'accounts/dashboard_admin.html', {
        'user': user,
        'stats': stats,
        'staff_list': serialize_list(staff_list),
        'crisis_stats': crisis_st,
    })

@login_required_mongo
@role_required('admin')
@require_http_methods(["GET", "POST"])
def admin_create_staff(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        full_name = request.POST.get('full_name', '').strip()
        department = request.POST.get('department', '').strip()
        designation = request.POST.get('designation', '').strip()
        phone = request.POST.get('phone', '').strip()

        if not all([email, password, full_name]):
            messages.error(request, "Name, email and password are required.")
        else:
            user, err = create_staff(
                email=email, password=password, full_name=full_name,
                department=department, designation=designation, phone=phone,
            )
            if err:
                messages.error(request, err)
            else:
                messages.success(request, f"Staff account created for {full_name}.")
                return redirect('accounts:admin_dashboard')

    return render(request, 'accounts/admin_create_staff.html')


@login_required_mongo
@role_required('admin')
def admin_list_staff(request):
    from core.utils import serialize_list
    return render(request, 'accounts/admin_list_staff.html', {
        'user': get_current_user(request),
        'staff_list': serialize_list(list_staff()),
    })


@login_required_mongo
@role_required('admin')
def admin_list_students(request):
    from core.utils import serialize_list
    return render(request, 'accounts/admin_list_students.html', {
        'user': get_current_user(request),
        'students': serialize_list(list_students()),
    })