from core.mongo import campus_bulletins
from core.utils import now


ALLOWED_CATEGORIES = {'news', 'event', 'breaking', 'special'}


def publish_bulletin(title, body, category, author):
    if category not in ALLOWED_CATEGORIES:
        raise ValueError('Choose a valid bulletin category.')
    document = {
        'title': title.strip(),
        'body': body.strip(),
        'category': category,
        'author_id': author['id'],
        'author_name': author.get('full_name', 'LPU Staff'),
        'published': True,
        'created_at': now(),
    }
    result = campus_bulletins().insert_one(document)
    document['_id'] = result.inserted_id
    return document


def latest_bulletins(limit=20):
    return list(campus_bulletins().find({'published': True}).sort('created_at', -1).limit(limit))
