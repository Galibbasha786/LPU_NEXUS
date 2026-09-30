# navigation/services.py
import math
import requests
import re
from datetime import datetime, timedelta
from core.mongo import navigation_routes, route_history, locations


# ============================================================
#  OSRM WALKING ROUTER (No API Key, Requires User-Agent)
# ============================================================
OSRM_FOOT_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/foot"

OSRM_HEADERS = {
    "User-Agent": "LPU-Nexus-Campus-Nav/1.0 (contact: syedsunnygalibbasha786@gmail.com)",
    "Accept": "application/json",
}
OSRM_TIMEOUT = 10


# ============================================================
#  COORDINATE NORMALIZATION (handles multiple schemas)
# ============================================================
def _extract_coordinates(loc):
    """
    Normalize coordinates from multiple schemas:
    - {"coordinates": [lon, lat]}                              ← primary
    - {"location": {"type": "Point", "coordinates": [lon, lat]}}   ← GeoJSON
    - {"coordinates": {"lon": x, "lat": y}}
    - {"lon": x, "lat": y}
    """
    if not loc:
        return None

    # Schema: top-level [lon, lat]
    c = loc.get("coordinates")
    if isinstance(c, (list, tuple)) and len(c) == 2:
        try:
            return [float(c[0]), float(c[1])]
        except (ValueError, TypeError):
            pass

    # Schema: GeoJSON {"location": {"coordinates": [lon, lat]}}
    geo = loc.get("location")
    if isinstance(geo, dict):
        gc = geo.get("coordinates")
        if isinstance(gc, (list, tuple)) and len(gc) == 2:
            try:
                return [float(gc[0]), float(gc[1])]
            except (ValueError, TypeError):
                pass

    # Schema: {"coordinates": {"lon": x, "lat": y}}
    if isinstance(c, dict):
        lon = c.get("lon") or c.get("lng") or c.get("longitude")
        lat = c.get("lat") or c.get("latitude")
        if lon is not None and lat is not None:
            try:
                return [float(lon), float(lat)]
            except (ValueError, TypeError):
                pass

    # Schema: top-level lon/lat
    lon = loc.get("lon") or loc.get("lng") or loc.get("longitude")
    lat = loc.get("lat") or loc.get("latitude")
    if lon is not None and lat is not None:
        try:
            return [float(lon), float(lat)]
        except (ValueError, TypeError):
            pass

    return None

# ============================================================
#  OSRM CALLS
# ============================================================
def get_walking_route(from_coords, to_coords):
    """Get walking route between two [lon, lat] points."""
    lon1, lat1 = from_coords
    lon2, lat2 = to_coords

    url = f"{OSRM_FOOT_URL}/{lon1},{lat1};{lon2},{lat2}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "true",
        "annotations": "true",
    }

    try:
        r = requests.get(
            url, params=params,
            headers=OSRM_HEADERS,
            timeout=OSRM_TIMEOUT,
        )

        if r.status_code == 429:
            return None, "Routing service rate limit reached. Try again in a moment."
        if r.status_code >= 400:
            return None, f"Routing service error ({r.status_code})."

        r.raise_for_status()
        data = r.json()

        if not data.get("routes"):
            return None, "No walking route found between these locations."

        route = data["routes"][0]
        return {
            "distance_m": route["distance"],
            "duration_s": route["duration"],
            "geometry": route["geometry"],
            "steps": route.get("legs", [{}])[0].get("steps", []),
        }, None

    except requests.exceptions.Timeout:
        return None, "Routing service timed out. Please retry."
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach routing service. Check internet connection."
    except Exception as e:
        return None, f"Routing error: {str(e)}"


def get_walking_route_via(from_coords, via_coords, to_coords):
    """Route with an intermediate waypoint."""
    lon1, lat1 = from_coords
    lon2, lat2 = via_coords
    lon3, lat3 = to_coords

    url = f"{OSRM_FOOT_URL}/{lon1},{lat1};{lon2},{lat2};{lon3},{lat3}"
    params = {"overview": "full", "geometries": "geojson"}

    try:
        r = requests.get(
            url, params=params,
            headers=OSRM_HEADERS,
            timeout=OSRM_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("routes"):
            return None, "No alternate route."
        route = data["routes"][0]
        return {
            "distance_m": route["distance"],
            "duration_s": route["duration"],
            "geometry": route["geometry"],
        }, None
    except Exception as e:
        return None, str(e)


# ============================================================
#  CAMPUS LOCATION LOOKUP
# ============================================================
def find_location(name_or_id):
    """
    Find a campus location by:
    1. _id (if valid ObjectId)
    2. Exact name (case-insensitive, trimmed)
    3. Prefix match (name starts with)
    4. Substring match (name contains)
    Returns doc or None.
    """
    from core.utils import to_object_id

    if not name_or_id:
        return None

    name_clean = str(name_or_id).strip()
    if not name_clean:
        return None

    # Remove "Your location" (used for live GPS)
    if name_clean.lower() in ("your location", "my location", "current location"):
        return None  # caller should use coords-based route

    # 1. Try by ObjectId
    oid = to_object_id(name_clean)
    if oid:
        doc = locations().find_one({"_id": oid})
        if doc:
            return doc

    # 2. Exact match (case-insensitive)
    doc = locations().find_one({
        "name": {"$regex": f"^{re.escape(name_clean)}$", "$options": "i"}
    })
    if doc:
        return doc

    # 3. Prefix match
    doc = locations().find_one({
        "name": {"$regex": f"^{re.escape(name_clean)}", "$options": "i"}
    })
    if doc:
        return doc

    # 4. Substring match (last resort)
    doc = locations().find_one({
        "name": {"$regex": re.escape(name_clean), "$options": "i"}
    })
    return doc


def get_all_locations():
    """Return only locations that have valid coordinates."""
    valid = []
    for doc in locations().find({}).sort("name", 1):
        if _extract_coordinates(doc):
            valid.append(doc)
    return valid


# ============================================================
#  SAFETY BUFFER CALCULATOR
# ============================================================
def calculate_safety_buffer(duration_s, congestion_level, has_obstacles):
    """Add buffer time based on congestion + active obstacles."""
    base_buffer = duration_s * 0.10

    congestion_mult = {
        "low": 1.0,
        "moderate": 1.3,
        "high": 1.7,
        "severe": 2.2,
    }.get(congestion_level, 1.0)

    obstacle_penalty = 60 if has_obstacles else 0

    return int(base_buffer * congestion_mult + obstacle_penalty)


# ============================================================
#  RECOMMENDED DEPARTURE TIME
# ============================================================
def calculate_departure_time(class_start_time, total_duration_s):
    """Given class start time and total walk time, return departure time."""
    if not class_start_time:
        return None
    if isinstance(class_start_time, str):
        try:
            class_start_time = datetime.fromisoformat(class_start_time)
        except Exception:
            return None

    leave_at = class_start_time - timedelta(seconds=total_duration_s + 120)
    return leave_at


# ============================================================
#  MAIN ROUTE ORCHESTRATOR
# ============================================================
def compute_smart_route(from_loc, to_loc, class_start_time=None):
    """
    Full pipeline:
    1. Get base walking route via OSRM
    2. Determine congestion level for current hour
    3. Apply safety buffer
    4. Find alternate routes if heavy congestion
    5. Return full intelligence payload

    ALWAYS returns (dict, error) or (None, error_string).
    Never returns None alone.
    """
    from .peak_hour import get_congestion_for_route
    from .obstacle_service import get_obstacles_for_route

    # --- validate coordinates ---
    from_coords = _extract_coordinates(from_loc)
    to_coords = _extract_coordinates(to_loc)

    if not from_coords or not to_coords:
        return {
            "error": "One or both locations have no coordinates. Please re-seed locations."
        }, 400

    # --- base route ---
    route, err = get_walking_route(from_coords, to_coords)
    if err or not route:
        return {"error": err or "Routing failed."}, 400

    base_duration_s = route["duration_s"]

    # --- congestion (defensive) ---
    try:
        congestion = get_congestion_for_route(
            from_loc.get("name", "?"), to_loc.get("name", "?")
        )
    except Exception as e:
        congestion = {
            "level": "low",
            "source": "fallback",
            "hour": 0,
            "minute": 0,
            "timestamp": "",
            "note": f"congestion error: {e}",
        }

    # --- obstacles (defensive) ---
    try:
        obstacles = get_obstacles_for_route(from_coords, to_coords)
    except Exception as e:
        obstacles = []

    # --- apply congestion slowdown ---
    congestion_slowdown = {
        "low": 1.0,
        "moderate": 1.15,
        "high": 1.35,
        "severe": 1.60,
    }.get(congestion.get("level", "low"), 1.0)

    adjusted_duration_s = base_duration_s * congestion_slowdown

    # --- safety buffer ---
    buffer_s = calculate_safety_buffer(
        adjusted_duration_s,
        congestion.get("level", "low"),
        bool(obstacles),
    )

    total_duration_s = adjusted_duration_s + buffer_s

    # --- departure time ---
    recommended_departure = calculate_departure_time(
        class_start_time, total_duration_s
    )

    # --- alternates if congestion high ---
    alternates = []
    if congestion.get("level") in ("high", "severe"):
        try:
            alternates = _find_alternate_routes(from_loc, to_loc)
        except Exception:
            alternates = []

    return {
        "from": {
            "name": from_loc.get("name", "Origin"),
            "coordinates": from_coords,
        },
        "to": {
            "name": to_loc.get("name", "Destination"),
            "coordinates": to_coords,
        },
        "base_duration_s": base_duration_s,
        "adjusted_duration_s": int(adjusted_duration_s),
        "total_duration_s": int(total_duration_s),
        "distance_m": route["distance_m"],
        "geometry": route["geometry"],
        "steps": route.get("steps", []),
        "congestion": congestion,
        "obstacles": obstacles,
        "safety_buffer_s": buffer_s,
        "recommended_departure": (
            recommended_departure.isoformat()
            if recommended_departure else None
        ),
        "alternates": alternates,
    }, None
def _find_alternate_routes(from_loc, to_loc):
    """Find alternative path via an intermediate offset waypoint."""
    alternates = []

    fc = _extract_coordinates(from_loc)
    tc = _extract_coordinates(to_loc)
    if not fc or not tc:
        return alternates

    mid_lon = (fc[0] + tc[0]) / 2
    mid_lat = (fc[1] + tc[1]) / 2

    alt_mid = [mid_lon + 0.001, mid_lat + 0.001]

    route, err = get_walking_route_via(fc, alt_mid, tc)
    if not err:
        alternates.append({
            "label": "Alternate (detour)",
            "duration_s": route["duration_s"],
            "distance_m": route["distance_m"],
            "geometry": route["geometry"],
        })

    return alternates