# navigation/obstacle_service.py
from datetime import datetime, timedelta
from core.mongo import problems, obstacles


BLOCKING_CATEGORIES = {
    "infrastructure": "Construction / blocked path",
    "cleanliness": "Spill / debris",
    "safety": "Unsafe area",
    "transport": "Vehicle blocking",
    "water": "Waterlogging",
}


def sync_obstacles_from_problems():
    """Convert active problem reports into navigation obstacles."""
    active_statuses = ["Reported", "Verified", "Assigned", "In Progress"]

    active_problems = problems().find({
        "status": {"$in": active_statuses},
        "category": {"$in": list(BLOCKING_CATEGORIES.keys())},
    })

    for p in active_problems:
        existing = obstacles().find_one({"problem_id": p["_id"]})
        if existing:
            obstacles().update_one(
                {"problem_id": p["_id"]},
                {"$set": {
                    "active": p["status"] != "Resolved",
                    "updated_at": datetime.utcnow(),
                }}
            )
            continue

        coords = None
        loc = p.get("location") or {}
        if isinstance(loc.get("coordinates"), (list, tuple)) and len(loc["coordinates"]) == 2:
            coords = loc["coordinates"]
        elif loc.get("lon") is not None and loc.get("lat") is not None:
            coords = [loc["lon"], loc["lat"]]

        if not coords:
            continue

        expires = datetime.utcnow() + timedelta(hours=24)
        obstacles().insert_one({
            "problem_id": p["_id"],
            "type": BLOCKING_CATEGORIES.get(p["category"], "obstacle"),
            "description": p.get("title", ""),
            "location": {"coordinates": coords},
            "severity": p.get("severity", "medium"),
            "active": True,
            "source": "problem_report",
            "created_at": datetime.utcnow(),
            "expires_at": expires,
        })


def get_obstacles_for_route(from_coords, to_coords, radius_m=150):
    """Find active obstacles near the route corridor."""
    if not from_coords or not to_coords:
        return []

    lons = [from_coords[0], to_coords[0]]
    lats = [from_coords[1], to_coords[1]]
    delta = radius_m / 111320

    min_lon = min(lons) - delta
    max_lon = max(lons) + delta
    min_lat = min(lats) - delta
    max_lat = max(lats) + delta

    now = datetime.utcnow()

    # Match EITHER schema: GeoJSON nested OR top-level
    query = {
        "active": True,
        "$and": [
            {"$or": [
                {"expires_at": {"$exists": False}},
                {"expires_at": {"$gt": now}},
            ]},
            {"$or": [
                # GeoJSON format
                {"location.coordinates": {
                    "$geoWithin": {
                        "$box": [[min_lon, min_lat], [max_lon, max_lat]]
                    }
                }},
                # Top-level format
                {"coordinates": {
                    "$geoWithin": {
                        "$box": [[min_lon, min_lat], [max_lon, max_lat]]
                    }
                }},
            ]},
        ],
    }

    try:
        cursor = obstacles().find(query)
    except Exception:
        return []

    results = []
    for o in cursor:
        # Extract coordinates defensively
        coords = None
        loc = o.get("location")
        if isinstance(loc, dict) and isinstance(loc.get("coordinates"), (list, tuple)):
            coords = loc["coordinates"]
        elif isinstance(o.get("coordinates"), (list, tuple)):
            coords = o["coordinates"]

        results.append({
            "id": str(o["_id"]),
            "type": o.get("type", "obstacle"),
            "description": o.get("description", ""),
            "severity": o.get("severity", "medium"),
            "coordinates": coords,
        })

    return results


def get_congestion_obstacles():
    """Return crowd-type obstacles."""
    now = datetime.utcnow()
    cursor = obstacles().find({
        "type": "crowd",
        "active": True,
        "$or": [
            {"expires_at": {"$exists": False}},
            {"expires_at": {"$gt": now}},
        ],
    })
    return list(cursor)