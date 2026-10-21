# crisis/views.py
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from accounts.session import login_required_mongo, get_current_user, role_required
from core.storage import save_incident_media
from core.mongo import users
from core.utils import serialize_doc, serialize_list

from . import services
from .constants import CATEGORIES, SEVERITIES, STATUSES, STAFF_TRANSITIONS
from .permissions import crisis_required, admin_required, audit


# =============================================================
#  STUDENT: REPORT + SEE VERIFIED INFO
# =============================================================
@login_required_mongo
@require_http_methods(["GET", "POST"])
def student_report(request):
    user = get_current_user(request)

    if request.method == "POST":
        category = request.POST.get("category", "other")
        severity = request.POST.get("severity", "medium")
        description = (request.POST.get("description") or "").strip()
        location_text = (request.POST.get("location_text") or "").strip()
        lon = request.POST.get("lon")
        lat = request.POST.get("lat")

        if not description:
            messages.error(request, "Description is required.")
        else:
            coordinates = None
            try:
                if lon and lat:
                    coordinates = [float(lon), float(lat)]
            except ValueError:
                coordinates = None

            media_path, err = save_incident_media(request.FILES.get("media"))
            if err:
                messages.error(request, err)
            else:
                incident = services.create_incident(
                    reported_by=user["id"],
                    category=category,
                    severity=severity,
                    description=description,
                    location_text=location_text,
                    coordinates=coordinates,
                    media_path=media_path,
                )
                messages.success(request, "Report submitted. Staff will verify shortly.")
                return redirect("crisis:my_reports")

    return render(request, "crisis/student_report.html", {
        "user": user,
        "categories": CATEGORIES,
        "severities": SEVERITIES,
    })


@login_required_mongo
def my_reports(request):
    user = get_current_user(request)
    incidents = services.list_my_incidents(user["id"])
    return render(request, "crisis/my_reports.html", {
        "user": user,
        "incidents": serialize_list(incidents),
    })


@login_required_mongo
def incident_detail(request, incident_id):
    """View a single incident — student sees their own; staff sees all."""
    user = get_current_user(request)
    incident = services.get_incident(incident_id)
    if not incident:
        messages.error(request, "Incident not found.")
        return redirect("accounts:dashboard")

    role = request.session.get("lpu_user_role")
    is_owner = str(incident.get("reported_by")) == user["id"]
    if role not in ("staff", "admin") and not is_owner:
        messages.error(request, "You don't have access to this incident.")
        return redirect("accounts:dashboard")

    timeline = services.list_incident_timeline(incident_id)
    return render(request, "crisis/incident_detail.html", {
        "user": user,
        "incident": serialize_doc(incident),
        "timeline": serialize_list(timeline),
        "can_manage": role in ("staff", "admin"),
        "statuses": STATUSES,
        "transitions": STAFF_TRANSITIONS.get(incident.get("status"), []),
    })


# =============================================================
#  STAFF: INCIDENT QUEUE
# =============================================================
@login_required_mongo
@crisis_required
def staff_queue(request):
    user = get_current_user(request)
    status_filter = request.GET.get("status")
    category_filter = request.GET.get("category")

    incidents = services.list_incidents(
        status=status_filter or None,
        category=category_filter or None,
        limit=200,
    )
    stats = services.crisis_stats()

    return render(request, "crisis/staff_queue.html", {
        "user": user,
        "incidents": serialize_list(incidents),
        "stats": stats,
        "categories": CATEGORIES,
        "statuses": STATUSES,
        "current_status": status_filter or "",
        "current_category": category_filter or "",
    })


@login_required_mongo
@crisis_required
@require_http_methods(["POST"])
def staff_verify(request, incident_id):
    user = get_current_user(request)
    new_status = request.POST.get("status", "verified")
    if new_status in ("resolved", "false_alarm") and user["role"] != "admin":
        messages.error(request, "Only admin can close incidents.")
        return redirect("crisis:incident_detail", incident_id=incident_id)

    services.verify_incident(incident_id, user["id"], new_status=new_status)
    messages.success(request, "Incident verified.")
    return redirect("crisis:incident_detail", incident_id=incident_id)


@login_required_mongo
@crisis_required
@require_http_methods(["POST"])
def staff_assign(request, incident_id):
    user = get_current_user(request)
    assignee_id = request.POST.get("assignee_id")

    if not assignee_id:
        messages.error(request, "Select a responder.")
        return redirect("crisis:incident_detail", incident_id=incident_id)

    services.assign_incident(incident_id, assignee_id, user["id"])
    messages.success(request, "Incident assigned.")
    return redirect("crisis:incident_detail", incident_id=incident_id)


@login_required_mongo
@crisis_required
@require_http_methods(["POST"])
def staff_update_status(request, incident_id):
    user = get_current_user(request)
    new_status = request.POST.get("status")
    note = request.POST.get("note", "")

    if not new_status:
        messages.error(request, "Pick a status.")
        return redirect("crisis:incident_detail", incident_id=incident_id)

    if new_status in ("resolved", "false_alarm") and user["role"] != "admin":
        messages.error(request, "Only admin can resolve/false-alarm.")
        return redirect("crisis:incident_detail", incident_id=incident_id)

    services.update_incident_status(incident_id, new_status, user["id"], note)
    messages.success(request, f"Status → {new_status}")
    return redirect("crisis:incident_detail", incident_id=incident_id)


@login_required_mongo
@crisis_required
@require_http_methods(["POST"])
def staff_add_note(request, incident_id):
    user = get_current_user(request)
    note = (request.POST.get("note") or "").strip()
    if note:
        services.add_incident_update(incident_id, user["id"], "note", note)
        messages.success(request, "Note added.")
    return redirect("crisis:incident_detail", incident_id=incident_id)


# =============================================================
#  STAFF/ADMIN: ANNOUNCEMENTS
# =============================================================
@login_required_mongo
@crisis_required
@require_http_methods(["GET", "POST"])
def announcement_new(request):
    user = get_current_user(request)

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        body = (request.POST.get("body") or "").strip()
        severity = request.POST.get("severity", "medium")
        kind = request.POST.get("kind", "advisory")
        expires_in = request.POST.get("expires_in_hours") or None

        if not title or not body:
            messages.error(request, "Title and body are required.")
        else:
            services.create_announcement(
                author_id=user["id"],
                title=title,
                body=body,
                severity=severity,
                kind=kind,
                published=True,
                expires_in_hours=expires_in,
            )
            messages.success(request, "Announcement published.")
            return redirect("crisis:staff_queue")

    return render(request, "crisis/announcement_new.html", {"user": user})


# =============================================================
#  ADMIN: CRISIS MODE + RESTRICTED ZONES
# =============================================================
@login_required_mongo
@admin_required
@require_http_methods(["POST"])
def admin_toggle_crisis(request):
    user = get_current_user(request)
    action = request.POST.get("action")
    message = request.POST.get("message", "")
    level = request.POST.get("level", "high")

    if action == "on":
        services.set_crisis_mode(True, user["id"], message, level)
        messages.warning(request, "🚨 Crisis Mode ACTIVATED.")
    else:
        services.set_crisis_mode(False, user["id"], message, "info")
        messages.success(request, "Crisis Mode deactivated.")

    return redirect("accounts:admin_dashboard")


@login_required_mongo
@admin_required
@require_http_methods(["GET", "POST"])
def admin_restricted_zones(request):
    user = get_current_user(request)

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        reason = (request.POST.get("reason") or "").strip()
        lon = request.POST.get("lon")
        lat = request.POST.get("lat")
        radius = request.POST.get("radius_m", "100")
        expires_in = request.POST.get("expires_in_hours") or None

        try:
            coords = [float(lon), float(lat)]
            radius_int = int(radius)
        except (TypeError, ValueError):
            messages.error(request, "Valid coordinates and radius required.")
            return redirect("crisis:admin_restricted_zones")

        if not name:
            messages.error(request, "Zone name required.")
        else:
            services.add_restricted_zone(
                name=name, coordinates=coords, radius_m=radius_int,
                reason=reason, created_by=user["id"],
                expires_in_hours=expires_in,
            )
            messages.success(request, "Restricted zone added.")
            return redirect("crisis:admin_restricted_zones")

    zones = services.list_restricted_zones(active_only=False)
    return render(request, "crisis/admin_restricted_zones.html", {
        "user": user,
        "zones": serialize_list(zones),
    })


@login_required_mongo
@admin_required
@require_http_methods(["POST"])
def admin_deactivate_zone(request, zone_id):
    user = get_current_user(request)
    services.deactivate_zone(zone_id, user["id"])
    messages.success(request, "Zone deactivated.")
    return redirect("crisis:admin_restricted_zones")


# =============================================================
#  API: LIVE FEED (for dashboards, polled)
# =============================================================
@login_required_mongo
def api_active_alerts(request):
    """
    Returns active announcements + crisis state + restricted zones.
    Polled every ~30s by dashboards.
    """
    state = services.get_crisis_state()
    anns = services.list_announcements(only_published=True, limit=10)
    zones = services.list_restricted_zones(active_only=True)

    return JsonResponse({
        "crisis_mode": bool(state.get("active")),
        "crisis_level": state.get("level", "info"),
        "crisis_message": state.get("message", ""),
        "announcements": serialize_list(anns),
        "restricted_zones": serialize_list(zones),
    })


@login_required_mongo
def api_incident_feed(request):
    """Recent verified incidents for map display."""
    role = request.session.get("lpu_user_role")
    q = {"verified": True}
    if role not in ("staff", "admin"):
        # Students see only safe info: no assigned_to, no internal notes
        pass
    incidents = list(
        __import__('core.mongo', fromlist=['incidents']).incidents()
        .find(q).sort("created_at", -1).limit(50)
    )
    return JsonResponse({"incidents": serialize_list(incidents)})