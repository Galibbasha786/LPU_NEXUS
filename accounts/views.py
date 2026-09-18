# accounts/views.py
import os
import uuid
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
from django.core.files.storage import default_storage
from django.views.decorators.http import require_http_methods

from .mongo_auth import (
    create_student, create_staff, authenticate_user,
    list_staff, list_students, get_student_profile,
)
from .session import (
    login_session, logout_session, get_current_user,
    login_required_mongo, role_required,
)
from core.mongo import users


ALLOWED_ID_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.pdf'}
MAX_ID_SIZE = 5 * 1024 * 1024   # 5 MB


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
        id_card = request.FILES.get('id_card')

        errors = []
        if not all([email, password, full_name, reg_no]):
            errors.append("Please fill all required fields.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if not id_card:
            errors.append("LPU ID card image is required.")

        id_card_path = ''
        if id_card:
            ext = os.path.splitext(id_card.name)[1].lower()
            if ext not in ALLOWED_ID_EXT:
                errors.append("ID card must be JPG, PNG, WEBP, or PDF.")
            elif id_card.size > MAX_ID_SIZE:
                errors.append("ID card must be under 5 MB.")
            else:
                # save to media/id_cards/<uuid>.<ext>
                fname = f"id_cards/{uuid.uuid4().hex}{ext}"
                saved = default_storage.save(fname, id_card)
                id_card_path = saved

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
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        user = authenticate_user(email, password)
        if user:
            login_session(request, user)
            messages.success(request, f"Welcome back, {user.get('full_name')}!")
            return redirect('accounts:dashboard')
        messages.error(request, "Invalid email or password.")

    return render(request, 'accounts/login.html')


def logout_view(request):
    logout_session(request)
    messages.info(request, "You've been logged out.")
    return redirect('accounts:login')


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

    stats = {
        'total_problems': 0,
        'open_problems': 0,
        'total_ideas': 0,
        'active_emergencies': 0,
        'total_users': users().count_documents({}),
        'total_students': student_count,
        'total_staff': len(staff_list),
    }
    from core.utils import serialize_list
    return render(request, 'accounts/dashboard_admin.html', {
        'user': user,
        'stats': stats,
        'staff_list': serialize_list(staff_list),
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