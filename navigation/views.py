# navigation/views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
import logging
logger = logging.getLogger(__name__)
from accounts.session import login_required_mongo

from .services import (
    compute_smart_route,
    find_location,
    get_all_locations,
    _extract_coordinates,
)
from .peak_hour import get_congestion_for_route, record_route_congestion
from .obstacle_service import (
    sync_obstacles_from_problems,
    get_obstacles_for_route,
)


@login_required_mongo
def campus_map_view(request):
    """Render the main navigation page."""
    locations = get_all_locations()
    return render(request, "navigation/map.html", {
        "locations": locations,
    })


@login_required_mongo
@require_http_methods(["POST"])
def api_route(request):
    """POST /navigation/api/route/ — full smart-route payload."""
    from_raw = (request.POST.get("from_id") or request.POST.get("from") or "").strip()
    to_raw = (request.POST.get("to_id") or request.POST.get("to") or "").strip()

    if not from_raw or not to_raw:
        return JsonResponse({"error": "Both origin and destination are required."}, status=400)

    from_loc = find_location(from_raw)
    to_loc = find_location(to_raw)

    if not from_loc:
        return JsonResponse({
            "error": f"Origin '{from_raw}' not found on campus map."
        }, status=404)

    if not to_loc:
        return JsonResponse({
            "error": f"Destination '{to_raw}' not found on campus map."
        }, status=404)

    if from_loc["_id"] == to_loc["_id"]:
        return JsonResponse({"error": "Origin and destination are the same."}, status=400)

    try:
        result = compute_smart_route(
            from_loc, to_loc,
            class_start_time=request.POST.get("class_start_time"),
        )
    except Exception as e:
        import traceback, logging
        logging.error("compute_smart_route crash: %s\n%s", e, traceback.format_exc())
        return JsonResponse({"error": f"Route engine error: {e}"}, status=500)

    # Defensive: guarantee tuple shape
    if not isinstance(result, tuple) or len(result) != 2:
        return JsonResponse({"error": "Route engine returned malformed result."}, status=500)

    payload, err = result

    if err:
        status = err if isinstance(err, int) else 400
        return JsonResponse({"error": payload.get("error", "Routing failed.")}, status=status)

    return JsonResponse(payload)


@login_required_mongo
@require_http_methods(["GET"])
def api_locations(request):
    """List all campus locations for autocomplete + map markers."""
    locs = get_all_locations()
    payload = []
    for l in locs:
        coords = _extract_coordinates(l)
        if not coords:
            continue
        payload.append({
            "id": str(l["_id"]),
            "name": l["name"],
            "category": l.get("category", "building"),
            "coordinates": coords,
        })

    return JsonResponse({"locations": payload})


@login_required_mongo
@require_http_methods(["POST"])
def api_report_congestion(request):
    """Students report congestion on a route."""
    from_name = request.POST.get("from")
    to_name = request.POST.get("to")
    level = request.POST.get("level", "moderate")

    if not from_name or not to_name:
        return JsonResponse({"error": "Missing route."}, status=400)

    record_route_congestion(from_name, to_name, level)
    return JsonResponse({"status": "recorded"})


@login_required_mongo
@require_http_methods(["POST"])
def api_sync_obstacles(request):
    """Trigger sync from problems to obstacles (admin/staff only)."""
    role = request.session.get("lpu_user_role")
    if role not in ("admin", "staff"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    sync_obstacles_from_problems()
    return JsonResponse({"status": "synced"})

@login_required_mongo
@require_http_methods(["POST"])
def api_route_from_coords(request):
    """
    POST /navigation/api/route-from-coords/
    Body: { from_lon, from_lat, to_id, class_start_time? }
    """
    try:
        from_lon = float(request.POST.get("from_lon"))
        from_lat = float(request.POST.get("from_lat"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid GPS coordinates."}, status=400)

    to_raw = (request.POST.get("to_id") or request.POST.get("to") or "").strip()
    to_loc = find_location(to_raw)

    if not to_loc:
        return JsonResponse({
            "error": f"Destination '{to_raw}' not found on campus map."
        }, status=404)

    from_loc = {
        "name": "Your location",
        "coordinates": [from_lon, from_lat],
    }

    try:
        result = compute_smart_route(
            from_loc, to_loc,
            class_start_time=request.POST.get("class_start_time"),
        )
    except Exception as e:
        import traceback, logging
        logging.error("compute_smart_route crash (coords): %s\n%s", e, traceback.format_exc())
        return JsonResponse({"error": f"Route engine error: {e}"}, status=500)

    if not isinstance(result, tuple) or len(result) != 2:
        return JsonResponse({"error": "Route engine returned malformed result."}, status=500)

    payload, err = result

    if err:
        status = err if isinstance(err, int) else 400
        return JsonResponse({"error": payload.get("error", "Routing failed.")}, status=status)

    return JsonResponse(payload)

@login_required_mongo
@require_http_methods(["POST"])
def api_create_obstacle(request):
    """
    POST /navigation/api/obstacles/create/
    Body: { type, description, lon, lat, severity? }
    Creates a temporary obstacle that affects routing.
    """
    from datetime import datetime, timedelta
    from core.mongo import obstacles

    obs_type = (request.POST.get("type") or "").strip()
    description = (request.POST.get("description") or "").strip()
    severity = (request.POST.get("severity") or "medium").strip()

    if not obs_type:
        return JsonResponse({"error": "Obstacle type is required."}, status=400)

    # Validate coordinates
    try:
        lon = float(request.POST.get("lon"))
        lat = float(request.POST.get("lat"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Valid location is required."}, status=400)

    # Validate lat/lon ranges
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return JsonResponse({"error": "Coordinates out of range."}, status=400)

    user_id = request.session.get("lpu_user_id")
    now = datetime.utcnow()

    # ============================================================
    #  STEP 2.4 — ANTI-SPAM: max 3 obstacles per user per hour
    # ============================================================
    one_hour_ago = now - timedelta(hours=1)
    recent_count = obstacles().count_documents({
        "reported_by": user_id,
        "source": "student_report",
        "created_at": {"$gte": one_hour_ago},
    })

    if recent_count >= 3:
        return JsonResponse({
            "error": "You've reported 3 obstacles in the last hour. Please wait before reporting more."
        }, status=429)
    # ============================================================

    # Temporary obstacles expire after 6 hours (auto-cleanup)
    expires = now + timedelta(hours=6)

    doc = {
        "problem_id": None,
        "type": obs_type,
        "description": description or f"Reported {obs_type}",
        "location": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "severity": severity,
        "active": True,
        "source": "student_report",
        "reported_by": user_id,
        "created_at": now,
        "expires_at": expires,
    }
    result = obstacles().insert_one(doc)

    return JsonResponse({
        "status": "created",
        "id": str(result.inserted_id),
        "expires_at": expires.isoformat(),
    })