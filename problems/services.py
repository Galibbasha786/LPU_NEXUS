import re

from core.mongo import (
    problem_comments,
    problem_history,
    problems,
    student_profiles,
)
from core.utils import now, to_object_id


def create_problem(reporter, title, description, category, location, priority):
    reporter_id = to_object_id(reporter["id"])
    if not reporter_id:
        raise ValueError("The reporter account could not be identified.")

    profile = student_profiles().find_one({"user_id": reporter_id}) or {}
    doc = {
        "title": title.strip(),
        "description": description.strip(),
        "category": category,
        "location": location.strip(),
        "priority": priority,
        "status": "submitted",
        "reported_by": reporter_id,
        "reporter_name": reporter.get("full_name", ""),
        "reporter_email": reporter.get("email", ""),
        "registration_number": profile.get("registration_number", ""),
        "assigned_to": None,
        "created_at": now(),
        "updated_at": now(),
    }
    result = problems().insert_one(doc)
    doc["_id"] = result.inserted_id
    _add_history(result.inserted_id, reporter_id, "submitted", "Problem report submitted.")
    return doc


def list_problems(status=None, category=None, search=None, limit=200):
    query = {}
    if status:
        query["status"] = status
    if category:
        query["category"] = category
    if search:
        safe_search = re.escape(search)
        query["$or"] = [
            {"title": {"$regex": safe_search, "$options": "i"}},
            {"description": {"$regex": safe_search, "$options": "i"}},
            {"location": {"$regex": safe_search, "$options": "i"}},
        ]
    return list(problems().find(query).sort("created_at", -1).limit(limit))


def list_my_problems(user_id, limit=100):
    reporter_id = to_object_id(user_id)
    if not reporter_id:
        return []
    return list(
        problems().find({"reported_by": reporter_id})
        .sort("created_at", -1).limit(limit)
    )


def get_problem(problem_id):
    oid = to_object_id(problem_id)
    return problems().find_one({"_id": oid}) if oid else None


def get_problem_updates(problem_id):
    oid = to_object_id(problem_id)
    if not oid:
        return []
    updates = list(problem_history().find({"problem_id": oid}).sort("created_at", 1))
    comments = list(problem_comments().find({"problem_id": oid}).sort("created_at", 1))
    for comment in comments:
        comment["kind"] = "comment"
        comment["message"] = comment.pop("body", "")
        updates.append(comment)
    return sorted(updates, key=lambda update: update["created_at"])


def add_problem_comment(problem_id, actor, body):
    oid = to_object_id(problem_id)
    actor_id = to_object_id(actor["id"])
    if not oid or not actor_id:
        raise ValueError("The problem or account could not be identified.")
    comment = {
        "problem_id": oid,
        "actor_id": actor_id,
        "actor_name": actor.get("full_name", ""),
        "actor_role": actor.get("role", ""),
        "body": body.strip(),
        "created_at": now(),
    }
    problem_comments().insert_one(comment)
    return comment


def update_problem(problem_id, actor, status=None, priority=None, assignee=None):
    oid = to_object_id(problem_id)
    actor_id = to_object_id(actor["id"])
    if not oid or not actor_id:
        return False
    changes = {"updated_at": now()}
    if status:
        changes["status"] = status
    if priority:
        changes["priority"] = priority
    if assignee is not None:
        changes["assigned_to"] = to_object_id(assignee) if assignee else None
    result = problems().update_one({"_id": oid}, {"$set": changes})
    if not result.matched_count:
        return False
    if status:
        _add_history(oid, actor_id, "status", f"Status updated to {status.replace('_', ' ')}.")
    if priority:
        _add_history(oid, actor_id, "priority", f"Priority updated to {priority}.")
    if assignee is not None:
        _add_history(oid, actor_id, "assignment", "Problem assignment updated.")
    return True


def problem_stats():
    open_statuses = ["submitted", "acknowledged", "in_progress", "waiting"]
    return {
        "total": problems().count_documents({}),
        "open": problems().count_documents({"status": {"$in": open_statuses}}),
        "submitted": problems().count_documents({"status": "submitted"}),
        "resolved": problems().count_documents({"status": "resolved"}),
    }


def _add_history(problem_id, actor_id, kind, message):
    problem_history().insert_one({
        "problem_id": problem_id,
        "actor_id": actor_id,
        "kind": kind,
        "message": message,
        "created_at": now(),
    })
