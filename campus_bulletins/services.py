from datetime import datetime

from core.mongo import campus_bulletins
from core.utils import now


ALLOWED_CATEGORIES = {'news', 'event', 'breaking', 'special'}


def cleanup_expired_bulletins(current=None):
    current = current or now()
    campus_bulletins().delete_many({'expires_at': {'$lte': current}})


def publish_bulletin(title, body, category, author, starts_at, expires_at):
    if category not in ALLOWED_CATEGORIES:
        raise ValueError('Choose a valid bulletin category.')
    if starts_at >= expires_at:
        raise ValueError('The end time must be after the start time.')
    cleanup_expired_bulletins()
    document = {
        'title': title.strip(),
        'body': body.strip(),
        'category': category,
        'author_id': author['id'],
        'author_name': author.get('full_name', 'LPU Staff'),
        'published': True,
        'starts_at': starts_at,
        'expires_at': expires_at,
        'created_at': now(),
    }
    result = campus_bulletins().insert_one(document)
    document['_id'] = result.inserted_id
    return document


def latest_bulletins(limit=20):
    current = now()
    cleanup_expired_bulletins(current)
    return list(campus_bulletins().find({
        'published': True,
        'starts_at': {'$lte': current},
        'expires_at': {'$gt': current},
    }).sort('created_at', -1).limit(limit))


def recent_bulletins(limit=50):
    cleanup_expired_bulletins()
    return list(campus_bulletins().find({}).sort('created_at', -1).limit(limit))
