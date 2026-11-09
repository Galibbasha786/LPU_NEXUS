# core/mongo.py
from pymongo import MongoClient, ASCENDING, DESCENDING
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

_client = None


def get_client():
    global _client
    if _client is None:
        _client = MongoClient(settings.MONGO_URI)
        logger.info("MongoDB client initialized")
    return _client


def get_db():
    return get_client()[settings.MONGO_DB_NAME]


# ---------- Collection accessors ----------
def users():              return get_db()['users']
def student_profiles():   return get_db()['student_profiles']
def problems():           return get_db()['problems']
def problem_comments():   return get_db()['problem_comments']
def problem_votes():      return get_db()['problem_votes']
def problem_history():    return get_db()['problem_history']
def ideas():              return get_db()['ideas']
def idea_votes():         return get_db()['idea_votes']
def teams():              return get_db()['teams']
def emergencies():        return get_db()['emergencies']
def emergency_updates():  return get_db()['emergency_updates']
def locations():          return get_db()['locations']
def notifications():      return get_db()['notifications']
def navigation_routes():  return get_db()['navigation_routes']
def route_history():      return get_db()['route_history']
def obstacles():          return get_db()['obstacles']
def incidents():        return get_db()['incidents']
def incident_updates(): return get_db()['incident_updates']
def announcements():    return get_db()['announcements']
def restricted_zones(): return get_db()['restricted_zones']
def crisis_state():     return get_db()['crisis_state']
def audit_log():        return get_db()['audit_log']
def placement_predictions(): return get_db()['placement_predictions']
def live_streams():         return get_db()['live_streams']
def live_comments():        return get_db()['live_comments']
def live_participants():    return get_db()['live_participants']
def social_posts():         return get_db()['social_posts']
def social_likes():         return get_db()['social_likes']
def social_comments():      return get_db()['social_comments']
def social_stories():       return get_db()['social_stories']
def social_chats():         return get_db()['social_chats']
def social_messages():      return get_db()['social_messages']
def social_blocks():        return get_db()['social_blocks']

def init_indexes():
    """Create MongoDB indexes. Safe to call repeatedly."""
    try:
        # users
        users().create_index([("email", ASCENDING)], unique=True)
        users().create_index([("role", ASCENDING)])
        users().create_index([("registration_number", ASCENDING)], sparse=True)
        # problems
        problems().create_index([("status", ASCENDING)])
        problems().create_index([("category", ASCENDING)])
        problems().create_index([("location.name", ASCENDING)])
        problems().create_index([("created_at", DESCENDING)])
        problems().create_index([("impact_score", DESCENDING)])
        problems().create_index([("reported_by", ASCENDING)])
        problems().create_index([("title", "text"), ("description", "text")])

        # votes (unique per user per target)
        problem_votes().create_index(
            [("problem_id", ASCENDING), ("user_id", ASCENDING)],
            unique=True,
        )
        idea_votes().create_index(
            [("idea_id", ASCENDING), ("user_id", ASCENDING)],
            unique=True,
        )

        # ideas
        ideas().create_index([("status", ASCENDING)])
        ideas().create_index([("problem_id", ASCENDING)])
        ideas().create_index([("created_at", DESCENDING)])

        # emergencies
        emergencies().create_index([("status", ASCENDING)])
        emergencies().create_index([("type", ASCENDING)])
        emergencies().create_index([("created_at", DESCENDING)])

        # locations
        locations().create_index([("name", ASCENDING)])
        locations().create_index([("category", ASCENDING)])
                # Navigation
        navigation_routes().create_index([("from_location", ASCENDING), ("to_location", ASCENDING)])
        route_history().create_index([("from_location", ASCENDING), ("to_location", ASCENDING), ("hour", ASCENDING)])
        obstacles().create_index([("location.coordinates", "2dsphere")])
        obstacles().create_index([("active", ASCENDING)])
        obstacles().create_index([("expires_at", ASCENDING)])

        # notifications
        notifications().create_index(
            [("user_id", ASCENDING), ("read", ASCENDING)]
        )
                # Crisis
        incidents().create_index([("status", ASCENDING)])
        incidents().create_index([("category", ASCENDING)])
        incidents().create_index([("severity", ASCENDING)])
        incidents().create_index([("created_at", DESCENDING)])
        incidents().create_index([("reported_by", ASCENDING)])
        incidents().create_index([("verified", ASCENDING)])
        incidents().create_index([("location.coordinates", "2dsphere")])

        incident_updates().create_index([("incident_id", ASCENDING), ("created_at", ASCENDING)])

        announcements().create_index([("published", ASCENDING)])
        announcements().create_index([("created_at", DESCENDING)])
        announcements().create_index([("severity", ASCENDING)])

        restricted_zones().create_index([("active", ASCENDING)])
        restricted_zones().create_index([("coordinates", "2dsphere")])

        audit_log().create_index([("actor_id", ASCENDING)])
        audit_log().create_index([("at", DESCENDING)])
        audit_log().create_index([("action", ASCENDING)])

        live_streams().create_index([("status", ASCENDING), ("created_at", DESCENDING)])
        live_comments().create_index([("stream_id", ASCENDING), ("_id", ASCENDING)])
        live_participants().create_index(
            [("stream_id", ASCENDING), ("user_id", ASCENDING)],
            unique=True,
        )
        live_participants().create_index(
            [("last_seen", ASCENDING)], expireAfterSeconds=86400,
        )

        # Social Hub
        social_posts().create_index([("created_at", DESCENDING)])
        social_posts().create_index([("author_id", ASCENDING), ("created_at", DESCENDING)])
        social_likes().create_index(
            [("post_id", ASCENDING), ("user_id", ASCENDING)],
            unique=True,
        )
        social_comments().create_index([("post_id", ASCENDING), ("created_at", DESCENDING)])
        social_stories().create_index(
            [("expires_at", ASCENDING)], expireAfterSeconds=0,
        )
        social_stories().create_index([("author_id", ASCENDING), ("expires_at", ASCENDING)])
        social_chats().create_index([("member_ids", ASCENDING), ("updated_at", DESCENDING)])
        social_chats().create_index([("direct_pair", ASCENDING)], unique=True, sparse=True)
        social_messages().create_index([("chat_id", ASCENDING), ("created_at", ASCENDING)])
        social_blocks().create_index(
            [("blocker_id", ASCENDING), ("blocked_id", ASCENDING)],
            unique=True,
        )

        logger.info("✅ MongoDB indexes ensured")
    except Exception:
        logger.exception("MongoDB index creation failed")
        raise
