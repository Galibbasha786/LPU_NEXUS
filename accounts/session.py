# accounts/session.py
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from core.utils import serialize_doc


SESSION_KEY = 'lpu_user_id'


def login_session(request, user_doc):
    """Store user id in Django session."""
    request.session[SESSION_KEY] = str(user_doc['_id'])
    request.session['lpu_user_role'] = user_doc.get('role', 'student')
    request.session['lpu_user_name'] = user_doc.get('full_name', '')


def logout_session(request):
    request.session.pop(SESSION_KEY, None)
    request.session.pop('lpu_user_role', None)
    request.session.pop('lpu_user_name', None)
    request.session.flush()


def get_current_user(request):
    """Fetch current logged-in user doc or None."""
    uid = request.session.get(SESSION_KEY)
    if not uid:
        return None
    from .mongo_auth import get_user_by_id
    user = get_user_by_id(uid)
    if user:
        return serialize_doc(user)
    return None


def login_required_mongo(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get(SESSION_KEY):
            messages.warning(request, "Please log in first.")
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper


def role_required(*allowed_roles):
    """Usage: @role_required('staff', 'admin')"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            role = request.session.get('lpu_user_role')
            if role not in allowed_roles:
                messages.error(request, "You don't have permission for that.")
                return redirect('accounts:dashboard')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
# accounts/session.py  (only add this function at the bottom — keep rest as-is)

def get_current_profile(request):
    """Returns the student_profile doc for current user, or None."""
    from .mongo_auth import get_student_profile
    uid = request.session.get(SESSION_KEY)
    if not uid:
        return None
    from core.utils import serialize_doc
    return serialize_doc(get_student_profile(uid))