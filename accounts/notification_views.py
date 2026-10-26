from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from core.utils import serialize_list

from .notification_services import (
    inbox_for_user,
    mark_notification_read,
    notify_roles,
)
from .session import get_current_user, login_required_mongo


@login_required_mongo
@require_http_methods(["GET", "POST"])
def notification_inbox(request):
    user = get_current_user(request)
    role = request.session.get("lpu_user_role")
    if request.method == "POST":
        if role not in ("staff", "admin"):
            messages.error(request, "Only staff and admins can send notifications.")
            return redirect("accounts:notifications")
        title = (request.POST.get("title") or "").strip()
        body = (request.POST.get("body") or "").strip()
        audience = request.POST.get("audience", "students")
        allowed_audiences = ("students", "staff", "both") if role == "admin" else ("students",)
        if not title or not body or len(title) > 140 or len(body) > 3000:
            messages.error(request, "Enter a title and message within the length limits.")
        elif audience not in allowed_audiences:
            messages.error(request, "You do not have permission to notify that audience.")
        else:
            target_roles = {
                "students": ["student"],
                "staff": ["staff"],
                "both": ["student", "staff"],
            }.get(audience, ["student"])
            recipient_count = notify_roles(
                target_roles, title, body, user, kind="announcement",
            )
            messages.success(request, f"Notification sent to {recipient_count} user(s).")
            return redirect("accounts:notifications")
    notifications, unread_count = inbox_for_user(request.session.get("lpu_user_id"))
    return render(request, "accounts/notifications.html", {
        "user": user,
        "notifications": serialize_list(notifications),
        "unread_count": unread_count,
        "can_send": role in ("staff", "admin"),
        "is_admin": role == "admin",
    })


@login_required_mongo
@require_http_methods(["POST"])
def mark_notification_read_view(request, notification_id):
    if not mark_notification_read(notification_id, request.session.get("lpu_user_id")):
        messages.error(request, "Notification not found.")
    return redirect("accounts:notifications")
