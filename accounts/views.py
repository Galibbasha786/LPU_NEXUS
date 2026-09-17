# accounts/views.py
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from .mongo_auth import create_user, authenticate_user
from .session import (
    login_session, logout_session, get_current_user,
    login_required_mongo,
)


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

        if not all([email, password, full_name]):
            messages.error(request, "Please fill all required fields.")
        elif password != confirm:
            messages.error(request, "Passwords do not match.")
        else:
            user, err = create_user(
                email=email, password=password, full_name=full_name,
                role='student', registration_number=reg_no,
                department=department, year=year,
            )
            if err:
                messages.error(request, err)
            else:
                login_session(request, user)
                messages.success(request, f"Welcome, {full_name}!")
                return redirect('accounts:dashboard')

    return render(request, 'accounts/register.html')


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


@login_required_mongo
def dashboard_view(request):
    user = get_current_user(request)
    return render(request, 'accounts/dashboard.html', {'user': user})