# crisis/permissions.py
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def crisis_required(view_func):
    """Only staff or admin can access crisis management views."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        role = request.session.get("lpu_user_role")
        if role not in ("staff", "admin"):
            messages.error(request, "You don't have permission to manage incidents.")
            return redirect("accounts:dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    """Only admin can access."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        role = request.session.get("lpu_user_role")
        if role != "admin":
            messages.error(request, "Admin access required.")
            return redirect("accounts:dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


def audit(action, target_type=None, target_id=None, detail=None):
    """Log a sensitive action to the audit_log collection."""
    from datetime import datetime
    from core.mongo import audit_log

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            response = view_func(request, *args, **kwargs)
            try:
                audit_log().insert_one({
                    "action": action,
                    "target_type": target_type,
                    "target_id": str(target_id) if target_id else None,
                    "detail": detail,
                    "actor_id": request.session.get("lpu_user_id"),
                    "actor_role": request.session.get("lpu_user_role"),
                    "actor_email": request.session.get("lpu_user_email"),
                    "at": datetime.utcnow(),
                    "ip": request.META.get("REMOTE_ADDR"),
                })
            except Exception:
                pass
            return response
        return wrapper
    return decorator