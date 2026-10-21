# crisis/services.py
from datetime import datetime, timedelta
from bson import ObjectId
from core.mongo import (
    incidents, incident_updates, announcements,
    restricted_zones, crisis_state,
)
from core.utils import now, serialize_doc, to_object_id


# =============================================================
#  INCIDENTS
# =============================================================
def create_incident(reported_by, category, severity, description,
                    location_text="", coordinates=None, media_path=None):
    """Student report. Always starts as 'reported' + unverified."""
    doc = {
        "reported_by": reported_by,
        "category": category,
        "severity": severity,
        "description": description,
        "location": {
            "text": location_text,
            "coordinates": coordinates,        # [lon, lat] or None
        },
        "media_path": media_path,
        "status": "reported",
        "verified": False,
        "verified_by": None,
        "verified_at": None,
        "assigned_to": None,
        "assigned_at": None,
        "responders": [],
        "closed_by": None,
        "closed_at": None,
        "created_at": now(),
        "updated_at": now(),
    }
    result = incidents().insert_one(doc)
    doc["_id"] = result.inserted_id

    # timeline
    add_incident_update(
        result.inserted_id, reported_by, "reported",
        f"Incident reported: {description[:100]}"
    )
    return doc


def add_incident_update(incident_id, actor_id, kind, message, extra=None):
    """Append a timeline entry."""
    oid = to_object_id(incident_id)
    doc = {
        "incident_id": oid,
        "actor_id": actor_id,
        "kind": kind,       # reported | verified | assigned | responding | note | resolved | ...
        "message": message,
        "extra": extra or {},
        "created_at": now(),
    }
    incident_updates().insert_one(doc)
    return doc


def get_incident(incident_id):
    oid = to_object_id(incident_id)
    if not oid:
        return None
    return incidents().find_one({"_id": oid})


def list_incidents(status=None, category=None, verified=None, limit=100):
    q = {}
    if status:
        q["status"] = status
    if category:
        q["category"] = category
    if verified is not None:
        q["verified"] = verified
    return list(incidents().find(q).sort("created_at", -1).limit(limit))


def list_my_incidents(user_id, limit=50):
    oid = to_object_id(user_id)
    if not oid:
        return []
    return list(
        incidents().find({"reported_by": oid}).sort("created_at", -1).limit(limit)
    )


def list_incident_timeline(incident_id):
    oid = to_object_id(incident_id)
    if not oid:
        return []
    return list(
        incident_updates().find({"incident_id": oid}).sort("created_at", 1)
    )


def verify_incident(incident_id, verified_by, new_status="verified"):
    """Staff marks an incident as verified/real."""
    oid = to_object_id(incident_id)
    incidents().update_one(
        {"_id": oid},
        {"$set": {
            "verified": True,
            "verified_by": verified_by,
            "verified_at": now(),
            "status": new_status,
            "updated_at": now(),
        }}
    )
    add_incident_update(oid, verified_by, "verified",
                        f"Incident verified by staff")
    return True


def assign_incident(incident_id, assignee_id, assigned_by):
    oid = to_object_id(incident_id)
    assignee_oid = to_object_id(assignee_id)
    incidents().update_one(
        {"_id": oid},
        {"$set": {
            "assigned_to": assignee_oid,
            "assigned_at": now(),
            "status": "assigned",
            "updated_at": now(),
        }}
    )
    add_incident_update(oid, assigned_by, "assigned",
                        f"Assigned to responder {assignee_id}")
    return True


def update_incident_status(incident_id, new_status, actor_id, note=""):
    oid = to_object_id(incident_id)
    incidents().update_one(
        {"_id": oid},
        {"$set": {"status": new_status, "updated_at": now()}}
    )
    add_incident_update(oid, actor_id, new_status, note or f"Status → {new_status}")
    return True


# =============================================================
#  ANNOUNCEMENTS (verified info to students)
# =============================================================
def create_announcement(author_id, title, body, severity="medium",
                        kind="advisory", published=True, expires_in_hours=None):
    exp = None
    if expires_in_hours:
        exp = now() + timedelta(hours=int(expires_in_hours))

    doc = {
        "author_id": author_id,
        "title": title.strip(),
        "body": body.strip(),
        "severity": severity,       # info | low | medium | high | critical
        "kind": kind,               # advisory | alert | restriction | update | all_clear
        "published": published,
        "verified": True,
        "created_at": now(),
        "updated_at": now(),
        "expires_at": exp,
    }
    result = announcements().insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def list_announcements(only_published=True, limit=50):
    q = {}
    if only_published:
        q["published"] = True
        q["$or"] = [
            {"expires_at": None},
            {"expires_at": {"$gt": now()}},
        ]
    return list(announcements().find(q).sort("created_at", -1).limit(limit))


# =============================================================
#  RESTRICTED ZONES
# =============================================================
def add_restricted_zone(name, coordinates, radius_m, reason,
                        created_by, expires_in_hours=None):
    """
    coordinates: [lon, lat]
    """
    exp = None
    if expires_in_hours:
        exp = now() + timedelta(hours=int(expires_in_hours))

    doc = {
        "name": name.strip(),
        "coordinates": coordinates,
        "radius_m": int(radius_m),
        "reason": reason.strip(),
        "created_by": created_by,
        "active": True,
        "created_at": now(),
        "expires_at": exp,
    }
    result = restricted_zones().insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def list_restricted_zones(active_only=True):
    q = {}
    if active_only:
        q["active"] = True
    return list(restricted_zones().find(q).sort("created_at", -1))


def deactivate_zone(zone_id, actor_id):
    oid = to_object_id(zone_id)
    restricted_zones().update_one(
        {"_id": oid},
        {"$set": {"active": False, "deactivated_at": now(), "deactivated_by": actor_id}}
    )


# =============================================================
#  CRISIS MODE
# =============================================================
def is_crisis_mode():
    state = crisis_state().find_one({"_id": "global"})
    if not state:
        return False
    return bool(state.get("active", False))


def set_crisis_mode(active, actor_id, message="", level="high"):
    crisis_state().update_one(
        {"_id": "global"},
        {"$set": {
            "active": bool(active),
            "level": level,
            "message": message,
            "activated_by": actor_id,
            "updated_at": now(),
        }},
        upsert=True,
    )
    return True


def get_crisis_state():
    return crisis_state().find_one({"_id": "global"}) or {
        "_id": "global", "active": False, "level": "info", "message": ""
    }


# =============================================================
#  STATS (for dashboards)
# =============================================================
def crisis_stats():
    from datetime import datetime
    one_day_ago = datetime.utcnow() - timedelta(days=1)

    return {
        "total_open": incidents().count_documents({
            "status": {"$nin": ["resolved", "false_alarm"]}
        }),
        "unverified": incidents().count_documents({
            "verified": False,
            "status": {"$nin": ["resolved", "false_alarm"]},
        }),
        "critical": incidents().count_documents({
            "severity": "critical",
            "status": {"$nin": ["resolved", "false_alarm"]},
        }),
        "resolved_24h": incidents().count_documents({
            "status": "resolved",
            "updated_at": {"$gte": one_day_ago},
        }),
        "active_announcements": announcements().count_documents({
            "published": True,
            "$or": [
                {"expires_at": None},
                {"expires_at": {"$gt": datetime.utcnow()}},
            ],
        }),
        "restricted_zones": restricted_zones().count_documents({"active": True}),
        "crisis_mode": is_crisis_mode(),
    }