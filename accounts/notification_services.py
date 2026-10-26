from core.mongo import notifications, users
from core.utils import now, to_object_id


def notify_roles(target_roles, title, body, sender, kind="announcement", target_url=""):
    recipient_list = list(users().find({
        "role": {"$in": target_roles},
        "active": {"$ne": False},
    }, {"_id": 1, "role": 1}))
    if not recipient_list:
        return 0
    created_at = now()
    documents = [{
        "user_id": recipient["_id"],
        "recipient_role": recipient["role"],
        "title": title.strip(),
        "body": body.strip(),
        "kind": kind,
        "target_url": target_url,
        "sender_id": to_object_id(sender["id"]),
        "sender_name": sender.get("full_name", ""),
        "sender_role": sender.get("role", ""),
        "read": False,
        "created_at": created_at,
    } for recipient in recipient_list]
    result = notifications().insert_many(documents, ordered=False)
    return len(result.inserted_ids)


def notify_user(user_id, title, body, sender, kind="announcement", target_url=""):
    recipient_id = to_object_id(user_id)
    if not recipient_id or not users().find_one({"_id": recipient_id, "active": {"$ne": False}}):
        return False
    notifications().insert_one({
        "user_id": recipient_id,
        "title": title.strip(),
        "body": body.strip(),
        "kind": kind,
        "target_url": target_url,
        "sender_id": to_object_id(sender["id"]),
        "sender_name": sender.get("full_name", ""),
        "sender_role": sender.get("role", ""),
        "read": False,
        "created_at": now(),
    })
    return True


def inbox_for_user(user_id, limit=50):
    oid = to_object_id(user_id)
    if not oid:
        return [], 0
    collection = notifications()
    items = list(collection.find({"user_id": oid}).sort("created_at", -1).limit(limit))
    unread_count = collection.count_documents({"user_id": oid, "read": False})
    return items, unread_count


def mark_notification_read(notification_id, user_id):
    notification_oid = to_object_id(notification_id)
    user_oid = to_object_id(user_id)
    if not notification_oid or not user_oid:
        return False
    result = notifications().update_one(
        {"_id": notification_oid, "user_id": user_oid},
        {"$set": {"read": True, "read_at": now()}},
    )
    return bool(result.matched_count)
