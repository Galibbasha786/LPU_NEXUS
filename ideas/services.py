from datetime import timedelta

from core.mongo import idea_votes, ideas
from core.utils import now, to_object_id

POLL_DURATION = timedelta(days=7)


def create_idea(author, title, description, category):
    author_id = to_object_id(author["id"])
    if not author_id:
        raise ValueError("The idea author could not be identified.")
    created = now()
    doc = {
        "title": title.strip(),
        "description": description.strip(),
        "category": category,
        "author_id": author_id,
        "author_name": author.get("full_name", ""),
        "author_email": author.get("email", ""),
        "status": "poll_open",
        "created_at": created,
        "poll_ends_at": created + POLL_DURATION,
        "comments": [],
    }
    result = ideas().insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def close_expired_polls():
    ideas().update_many(
        {"status": "poll_open", "poll_ends_at": {"$lte": now()}},
        {"$set": {"status": "pending_review", "updated_at": now()}},
    )


def list_ideas(limit=100):
    close_expired_polls()
    return list(ideas().find({}).sort("created_at", -1).limit(limit))


def get_idea(idea_id):
    close_expired_polls()
    oid = to_object_id(idea_id)
    return ideas().find_one({"_id": oid}) if oid else None


def add_vote(idea_id, user_id, support):
    idea_oid = to_object_id(idea_id)
    user_oid = to_object_id(user_id)
    if not idea_oid or not user_oid:
        return False, "The idea or student account could not be identified."
    idea = get_idea(idea_id)
    if not idea:
        return False, "Idea not found."
    poll_ends_at = idea.get("poll_ends_at")
    if idea.get("status") != "poll_open" or not poll_ends_at or poll_ends_at <= now():
        close_expired_polls()
        return False, "This poll is closed."
    if idea.get("author_id") == user_oid:
        return False, "You cannot vote on your own idea."
    idea_votes().update_one(
        {"idea_id": idea_oid, "user_id": user_oid},
        {"$set": {"support": bool(support), "updated_at": now()},
         "$setOnInsert": {"created_at": now()}},
        upsert=True,
    )
    return True, None


def vote_totals(idea_id):
    oid = to_object_id(idea_id)
    if not oid:
        return {"support": 0, "against": 0, "total": 0}
    support = idea_votes().count_documents({"idea_id": oid, "support": True})
    against = idea_votes().count_documents({"idea_id": oid, "support": False})
    return {"support": support, "against": against, "total": support + against}


def get_user_vote(idea_id, user_id):
    idea_oid = to_object_id(idea_id)
    user_oid = to_object_id(user_id)
    if not idea_oid or not user_oid:
        return None
    vote = idea_votes().find_one({"idea_id": idea_oid, "user_id": user_oid})
    return vote.get("support") if vote else None


def add_comment(idea_id, author, body):
    idea_oid = to_object_id(idea_id)
    author_id = to_object_id(author["id"])
    if not idea_oid or not author_id:
        return False
    idea = get_idea(idea_id)
    if not idea or idea.get("status") != "poll_open":
        return False
    comment = {
        "author_id": author_id,
        "author_name": author.get("full_name", ""),
        "body": body.strip(),
        "created_at": now(),
    }
    result = ideas().update_one(
        {"_id": idea_oid, "status": "poll_open"},
        {"$push": {"comments": comment}, "$set": {"updated_at": now()}},
    )
    return bool(result.modified_count)


def review_idea(idea_id, reviewer_id, decision, note):
    oid = to_object_id(idea_id)
    reviewer_oid = to_object_id(reviewer_id)
    if not oid or not reviewer_oid:
        return False
    close_expired_polls()
    result = ideas().update_one(
        {"_id": oid, "status": "pending_review"},
        {"$set": {
            "status": decision,
            "decision_note": note.strip(),
            "reviewed_by": reviewer_oid,
            "reviewed_at": now(),
            "updated_at": now(),
        }},
    )
    return bool(result.modified_count)
