# core/utils.py
from datetime import datetime
from bson import ObjectId


def now():
    return datetime.utcnow()


def serialize_doc(doc):
    """Convert MongoDB doc -> JSON-safe dict (handles ObjectId, datetime)."""
    if doc is None:
        return None
    doc = dict(doc)
    if '_id' in doc:
        doc['id'] = str(doc['_id'])
        del doc['_id']
    for k, v in list(doc.items()):
        if isinstance(v, ObjectId):
            doc[k] = str(v)
        elif isinstance(v, datetime):
            doc[k] = v.isoformat()
        elif isinstance(v, dict):
            doc[k] = serialize_doc(v)
        elif isinstance(v, list):
            doc[k] = [
                serialize_doc(i) if isinstance(i, dict)
                else (str(i) if isinstance(i, ObjectId) else
                      (i.isoformat() if isinstance(i, datetime) else i))
                for i in v
            ]
    return doc


def serialize_list(cursor):
    return [serialize_doc(d) for d in cursor]


def to_object_id(value):
    try:
        return ObjectId(str(value))
    except Exception:
        return None