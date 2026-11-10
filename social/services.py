from datetime import timedelta
import ipaddress
import re
import uuid
from urllib.parse import unquote, urlparse

import requests
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from core.mongo import (
    social_blocks,
    social_follows,
    social_chats,
    social_comments,
    social_likes,
    social_messages,
    social_posts,
    social_stories,
    student_profiles,
    users,
)
from core.utils import now, to_object_id

STORY_LIFETIME = timedelta(hours=24)
FEED_LIMIT = 40
CHAT_HISTORY_LIMIT = 100
MAX_GROUP_SIZE = 30
CALL_LIFETIME = timedelta(hours=1)
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
VIDEO_SUFFIXES = {'.mp4', '.webm', '.mov'}


class SocialAccessError(ValueError):
    """Raised when an account cannot access a social resource."""


def verified_student(user_id):
    oid = to_object_id(user_id)
    if not oid:
        return None
    return users().find_one({
        '_id': oid,
        'role': 'student',
        'active': {'$ne': False},
        '$or': [
            {'id_verification_status': 'verified'},
            {'id_verification_status': {'$exists': False}},
        ],
    })


def _require_student(user_id):
    user = verified_student(user_id)
    if not user:
        raise SocialAccessError('Only verified, active LPU student accounts can use Social Hub.')
    return user


def _blocked_peer_ids(user_id):
    oid = to_object_id(user_id)
    if not oid:
        return set()
    return {
        block['blocked_id'] if block['blocker_id'] == oid else block['blocker_id']
        for block in social_blocks().find({
            '$or': [{'blocker_id': oid}, {'blocked_id': oid}],
        })
    }


def _is_blocked(first_id, second_id):
    return bool(social_blocks().find_one({
        '$or': [
            {'blocker_id': first_id, 'blocked_id': second_id},
            {'blocker_id': second_id, 'blocked_id': first_id},
        ],
    }))


def _require_unblocked(first_id, second_id):
    if _is_blocked(first_id, second_id):
        raise SocialAccessError('This action is unavailable because one of these students blocked the other.')


def _post_for_interaction(user_id, post_id):
    post_oid = to_object_id(post_id)
    post = social_posts().find_one({'_id': post_oid}) if post_oid else None
    if not post:
        raise ValueError('That post is no longer available.')
    original_id = post.get('original_post_id') or post['_id']
    original = social_posts().find_one({'_id': original_id, 'kind': 'post'})
    if not original:
        raise ValueError('That post is no longer available.')
    if not verified_student(post['author_id']) or not verified_student(original['author_id']):
        raise ValueError('That post is no longer available.')
    _require_unblocked(to_object_id(user_id), post['author_id'])
    _require_unblocked(to_object_id(user_id), original['author_id'])
    return post, original


def students_for_people(user_id, limit=200):
    current_oid = to_object_id(user_id)
    if not current_oid:
        return []
    _require_student(current_oid)
    students = list(users().find({
        '_id': {'$ne': current_oid},
        'role': 'student',
        'active': {'$ne': False},
        '$or': [
            {'id_verification_status': 'verified'},
            {'id_verification_status': {'$exists': False}},
        ],
    }).sort('full_name', ASCENDING).limit(limit))
    student_ids = [student['_id'] for student in students]
    profiles = {
        profile['user_id']: profile
        for profile in student_profiles().find({'user_id': {'$in': student_ids}})
    } if student_ids else {}
    blocks = list(social_blocks().find({
        '$or': [
            {'blocker_id': current_oid, 'blocked_id': {'$in': student_ids}},
            {'blocked_id': current_oid, 'blocker_id': {'$in': student_ids}},
        ],
    })) if student_ids else []
    blocked_by_me = {block['blocked_id'] for block in blocks if block['blocker_id'] == current_oid}
    blocked_me = {block['blocker_id'] for block in blocks if block['blocked_id'] == current_oid}
    follows = {edge['followed_id'] for edge in social_follows().find({'follower_id': current_oid, 'followed_id': {'$in': student_ids}})} if student_ids else set()

    return [{
        'id': str(student['_id']),
        'full_name': student.get('full_name', 'LPU student'),
        'profile_image_url': student.get('profile_image_url', ''),
        'registration_number': profiles.get(student['_id'], {}).get('registration_number', ''),
        'blocked_by_me': student['_id'] in blocked_by_me,
        'blocked_me': student['_id'] in blocked_me,
        'following': student['_id'] in follows,
    } for student in students]


def resolve_tagged_students(user_id, registration_numbers):
    _require_student(user_id)
    numbers = list(dict.fromkeys(
        number.strip() for number in registration_numbers if number.strip()
    ))
    if len(numbers) > 20:
        raise ValueError('Tag up to 20 students in one post.')
    if not numbers:
        return []

    profiles = list(student_profiles().find({
        'registration_number': {'$in': numbers},
    }))
    user_ids = [profile['user_id'] for profile in profiles]
    valid_students = list(users().find({
        '_id': {'$in': user_ids},
        'role': 'student',
        'active': {'$ne': False},
        '$or': [
            {'id_verification_status': 'verified'},
            {'id_verification_status': {'$exists': False}},
        ],
    })) if user_ids else []
    resolved_ids = {student['_id'] for student in valid_students}
    ids_by_number = {
        profile['registration_number']: profile['user_id']
        for profile in profiles
        if profile['user_id'] in resolved_ids
    }
    missing = [number for number in numbers if number not in ids_by_number]
    if missing:
        raise ValueError('One or more registration numbers do not match a verified LPU student.')
    author_oid = to_object_id(user_id)
    if author_oid in ids_by_number.values():
        raise ValueError('You cannot tag yourself.')
    return list(dict.fromkeys(ids_by_number.values()))


def search_students_for_tag(user_id, query):
    _require_student(user_id)
    query = query.strip()[:30]
    if not query:
        return []
    profiles = list(student_profiles().find({
        'registration_number': {
            '$regex': f'^{re.escape(query)}',
            '$options': 'i',
        },
    }).limit(10))
    profile_by_user = {profile['user_id']: profile for profile in profiles}
    students = users().find({
        '_id': {
            '$in': list(profile_by_user),
            '$ne': to_object_id(user_id),
        },
        'role': 'student',
        'active': {'$ne': False},
        '$or': [
            {'id_verification_status': 'verified'},
            {'id_verification_status': {'$exists': False}},
        ],
    }).sort('full_name', ASCENDING)
    return [{
        'id': str(student['_id']),
        'full_name': student.get('full_name', 'LPU student'),
        'registration_number': profile_by_user[student['_id']].get('registration_number', ''),
        'profile_image_url': student.get('profile_image_url', ''),
        'department': profile_by_user[student['_id']].get('department', ''),
        'year': profile_by_user[student['_id']].get('year', ''),
    } for student in students]


def student_for_registration(user_id, registration_number):
    _require_student(user_id)
    registration_number = registration_number.strip()
    if not registration_number or len(registration_number) > 30:
        raise ValueError('Enter a valid student registration number.')
    profile = student_profiles().find_one({
        'registration_number': {
            '$regex': f'^{re.escape(registration_number)}$',
            '$options': 'i',
        },
    })
    peer_id = profile.get('user_id') if profile else None
    peer = verified_student(peer_id) if peer_id else None
    if not peer:
        raise ValueError('No verified student matches that registration number.')
    return peer


def create_post(author, caption, media=None, tagged_user_ids=None):
    author_doc = _require_student(author['id'])
    doc = {
        'kind': 'post',
        'author_id': author_doc['_id'],
        'author_name': author_doc.get('full_name', 'LPU student'),
        'author_image': author_doc.get('profile_image_url', ''),
        'caption': caption.strip(),
        'tagged_user_ids': tagged_user_ids or [],
        'media_url': media.get('url', '') if media else '',
        'media_public_id': media.get('public_id', '') if media else '',
        'media_type': media.get('media_type', '') if media else '',
        'created_at': now(),
    }
    result = social_posts().insert_one(doc)
    doc['_id'] = result.inserted_id
    return doc


def create_story(author, caption, media):
    author_doc = _require_student(author['id'])
    created_at = now()
    doc = {
        'author_id': author_doc['_id'],
        'author_name': author_doc.get('full_name', 'LPU student'),
        'author_image': author_doc.get('profile_image_url', ''),
        'caption': caption.strip(),
        'media_url': media.get('url', ''),
        'media_public_id': media.get('public_id', ''),
        'media_type': media.get('media_type', ''),
        'created_at': created_at,
        'expires_at': created_at + STORY_LIFETIME,
    }
    result = social_stories().insert_one(doc)
    doc['_id'] = result.inserted_id
    return doc


def list_stories(user_id, limit=60):
    user_oid = to_object_id(user_id)
    _require_student(user_oid)
    blocked_ids = _blocked_peer_ids(user_oid)
    stories = list(social_stories().find({
        'expires_at': {'$gt': now()},
        'author_id': {'$nin': list(blocked_ids)},
    }).sort('created_at', DESCENDING).limit(limit))
    story_author_ids = list({story['author_id'] for story in stories})
    valid_author_ids = {
        user['_id'] for user in users().find({
            '_id': {'$in': story_author_ids},
            'role': 'student',
            'active': {'$ne': False},
            '$or': [
                {'id_verification_status': 'verified'},
                {'id_verification_status': {'$exists': False}},
            ],
        })
    } if story_author_ids else set()
    return [story for story in stories if story['author_id'] in valid_author_ids]


def create_reshare(user, post_id, caption=''):
    author = _require_student(user['id'])
    _, original = _post_for_interaction(author['_id'], post_id)
    doc = {
        'kind': 'reshare',
        'author_id': author['_id'],
        'author_name': author.get('full_name', 'LPU student'),
        'caption': caption.strip(),
        'original_post_id': original['_id'],
        'created_at': now(),
    }
    result = social_posts().insert_one(doc)
    doc['_id'] = result.inserted_id
    return doc


def share_post_in_direct_chat(user_id, post_id, peer_id):
    author = _require_student(user_id)
    peer = _require_student(peer_id)
    if author['_id'] == peer['_id']:
        raise ValueError('Choose another student to share this post with.')
    _require_unblocked(author['_id'], peer['_id'])

    post, original = _post_for_interaction(author['_id'], post_id)
    shared_post = {
        'id': str(post['_id']),
        'author_name': post.get('author_name', 'LPU student'),
        'caption': post.get('caption', ''),
        'media_url': post.get('media_url') or original.get('media_url', ''),
        'media_type': post.get('media_type') or original.get('media_type', ''),
    }
    chat = create_direct_chat(str(author['_id']), str(peer['_id']))
    created_at = now()
    message = {
        'chat_id': chat['_id'],
        'sender_id': author['_id'],
        'sender_name': author.get('full_name', 'LPU student'),
        'body': '',
        'gif_url': '',
        'media_url': '',
        'media_type': '',
        'media_public_id': '',
        'shared_post': shared_post,
        'created_at': created_at,
    }
    social_chats().update_one(
        {'_id': chat['_id']},
        {'$set': {'updated_at': created_at}},
    )
    result = social_messages().insert_one(message)
    message['id'] = str(result.inserted_id)
    message['sender_id'] = str(message['sender_id'])
    message.pop('chat_id', None)
    return chat, message


def _count_by_post(collection, post_ids):
    if not post_ids:
        return {}
    return {
        row['_id']: row['count']
        for row in collection().aggregate([
            {'$match': {'post_id': {'$in': post_ids}}},
            {'$group': {'_id': '$post_id', 'count': {'$sum': 1}}},
        ])
    }


def list_feed(user_id, post_id=None):
    user_oid = to_object_id(user_id)
    _require_student(user_oid)
    blocked_ids = _blocked_peer_ids(user_oid)
    query = {
        'author_id': {'$nin': list(blocked_ids)},
    }
    if post_id is not None:
        post_oid = to_object_id(post_id)
        if not post_oid:
            return []
        query['_id'] = post_oid
    feed_cursor = social_posts().find(query).sort('created_at', DESCENDING)
    if post_id is None:
        feed_cursor = feed_cursor.limit(FEED_LIMIT)
    feed_docs = list(feed_cursor)
    if not feed_docs:
        return []

    original_ids = {
        post.get('original_post_id') or post['_id']
        for post in feed_docs
    }
    originals = {
        post['_id']: post for post in social_posts().find({
            '_id': {'$in': list(original_ids)},
            'kind': 'post',
        })
    }
    author_ids = {
        post['author_id'] for post in feed_docs
    } | {
        post['author_id'] for post in originals.values()
    } | {
        tagged_id
        for post in feed_docs
        for tagged_id in post.get('tagged_user_ids', [])
    } | {
        tagged_id
        for post in originals.values()
        for tagged_id in post.get('tagged_user_ids', [])
    }
    authors = {
        author['_id']: author
        for author in users().find({
            '_id': {'$in': list(author_ids)},
        })
    }
    valid_author_ids = {
        author_id for author_id, author in authors.items()
        if author.get('role') == 'student'
        and author.get('active', True) is not False
        and author.get('id_verification_status', 'verified') == 'verified'
    }
    current_user_likes = {
        like['post_id'] for like in social_likes().find({
            'user_id': user_oid,
            'post_id': {'$in': [post['_id'] for post in feed_docs]},
        })
    }
    likes_by_post = _count_by_post(social_likes, [post['_id'] for post in feed_docs])
    comments_by_post = _count_by_post(social_comments, [post['_id'] for post in feed_docs])
    result = []
    for post in feed_docs:
        original = originals.get(post.get('original_post_id') or post['_id'])
        if (
            not original
            or original.get('author_id') in blocked_ids
            or post['author_id'] not in valid_author_ids
            or original['author_id'] not in valid_author_ids
        ):
            continue
        comments = list(social_comments().find({
            'post_id': post['_id'],
        }).sort('created_at', DESCENDING).limit(3))
        post['id'] = str(post.pop('_id'))
        post['author_id'] = str(post['author_id'])
        post['author_image'] = authors.get(
            ObjectId(post['author_id']), {},
        ).get('profile_image_url', '')
        post['tagged_names'] = [
            authors[tagged_id].get('full_name', 'LPU student')
            for tagged_id in post.get('tagged_user_ids', [])
            if tagged_id in valid_author_ids
        ]
        post['likes_count'] = likes_by_post.get(ObjectId(post['id']), 0)
        post['comments_count'] = comments_by_post.get(ObjectId(post['id']), 0)
        post['liked_by_me'] = ObjectId(post['id']) in current_user_likes
        post['comments'] = list(reversed(comments))
        if post.get('kind') == 'reshare':
            post['original'] = original
            post['original']['id'] = str(post['original'].pop('_id'))
            post['original']['author_id'] = str(post['original']['author_id'])
            post['original']['author_image'] = authors.get(
                ObjectId(post['original']['author_id']), {},
            ).get('profile_image_url', '')
            post['original']['tagged_names'] = [
                authors[tagged_id].get('full_name', 'LPU student')
                for tagged_id in post['original'].get('tagged_user_ids', [])
                if tagged_id in valid_author_ids
            ]
        result.append(post)
    return result


def toggle_like(user_id, post_id):
    user = _require_student(user_id)
    post, _ = _post_for_interaction(user['_id'], post_id)
    post_oid = post['_id']
    query = {'post_id': post_oid, 'user_id': user['_id']}
    if social_likes().find_one(query):
        social_likes().delete_one(query)
        return False
    try:
        social_likes().insert_one({**query, 'created_at': now()})
    except DuplicateKeyError:
        return True
    return True


def add_comment(user, post_id, body):
    author = _require_student(user['id'])
    post, _ = _post_for_interaction(author['_id'], post_id)
    post_oid = post['_id']
    body = body.strip()
    if not body or len(body) > 2000:
        raise ValueError('Enter a comment of up to 2,000 characters.')
    comment = {
        'post_id': post_oid,
        'author_id': author['_id'],
        'author_name': author.get('full_name', 'LPU student'),
        'body': body.strip(),
        'created_at': now(),
    }
    result = social_comments().insert_one(comment)
    comment['_id'] = result.inserted_id
    return comment


def create_direct_chat(user_id, peer_id):
    current = _require_student(user_id)
    peer = _require_student(peer_id)
    if current['_id'] == peer['_id']:
        raise ValueError('Choose another student to start a chat.')
    _require_unblocked(current['_id'], peer['_id'])
    member_ids = sorted([current['_id'], peer['_id']], key=str)
    pair = ':'.join(str(member_id) for member_id in member_ids)
    chat = social_chats().find_one({'direct_pair': pair})
    if chat:
        return chat
    created_at = now()
    doc = {
        'kind': 'direct',
        'direct_pair': pair,
        'member_ids': member_ids,
        'owner_id': current['_id'],
        'created_at': created_at,
        'updated_at': created_at,
    }
    try:
        result = social_chats().insert_one(doc)
    except DuplicateKeyError:
        chat = social_chats().find_one({'direct_pair': pair})
        if not chat:
            raise SocialAccessError('The conversation could not be created. Please try again.')
        return chat
    doc['_id'] = result.inserted_id
    return doc


def create_group(user_id, name, member_ids):
    owner = _require_student(user_id)
    ids = []
    for member_id in member_ids:
        oid = to_object_id(member_id)
        if not oid:
            raise ValueError('One or more selected group members are invalid.')
        if oid not in ids:
            ids.append(oid)
    if owner['_id'] not in ids:
        ids.append(owner['_id'])
    if len(ids) < 3:
        raise ValueError('A group chat needs you and at least two other students.')
    if len(ids) > MAX_GROUP_SIZE:
        raise ValueError(f'Group chats are limited to {MAX_GROUP_SIZE} students.')
    valid_ids = {
        student['_id'] for student in users().find({
            '_id': {'$in': ids},
            'role': 'student',
            'active': {'$ne': False},
            '$or': [
                {'id_verification_status': 'verified'},
                {'id_verification_status': {'$exists': False}},
            ],
        })
    }
    if valid_ids != set(ids):
        raise ValueError('Every group member must be an active, verified LPU student.')
    if any(_is_blocked(owner['_id'], member_id) for member_id in ids if member_id != owner['_id']):
        raise ValueError('A group cannot be created with a student who has blocked you or whom you blocked.')
    created_at = now()
    doc = {
        'kind': 'group',
        'name': name.strip(),
        'member_ids': ids,
        'owner_id': owner['_id'],
        'created_at': created_at,
        'updated_at': created_at,
    }
    result = social_chats().insert_one(doc)
    doc['_id'] = result.inserted_id
    return doc


def list_chats(user_id):
    user_oid = to_object_id(user_id)
    _require_student(user_oid)
    chats = list(social_chats().find({
        'member_ids': user_oid,
    }).sort('updated_at', DESCENDING).limit(100))
    peer_ids = {
        member_id
        for chat in chats if chat.get('kind') == 'direct'
        for member_id in chat.get('member_ids', [])
        if member_id != user_oid
    }
    peers = {
        user['_id']: user
        for user in users().find({
            '_id': {'$in': list(peer_ids)},
            'role': 'student',
            'active': {'$ne': False},
            '$or': [
                {'id_verification_status': 'verified'},
                {'id_verification_status': {'$exists': False}},
            ],
        })
    } if peer_ids else {}
    blocked_ids = _blocked_peer_ids(user_oid)
    result = []
    for chat in chats:
        if chat.get('kind') == 'direct':
            other_id = next(
                (member_id for member_id in chat.get('member_ids', []) if member_id != user_oid),
                None,
            )
            if not other_id or other_id in blocked_ids or other_id not in peers:
                continue
            peer = peers.get(other_id)
            chat['display_name'] = peer.get('full_name', 'LPU student')
        else:
            chat['display_name'] = chat.get('name', 'Student group')
        chat['id'] = str(chat.pop('_id'))
        result.append(chat)
    return result


def get_chat(user_id, chat_id):
    user = _require_student(user_id)
    chat_oid = to_object_id(chat_id)
    chat = social_chats().find_one({
        '_id': chat_oid,
        'member_ids': user['_id'],
    }) if chat_oid else None
    if not chat:
        return None
    if chat.get('kind') == 'direct':
        peer_id = next(
            (member_id for member_id in chat.get('member_ids', []) if member_id != user['_id']),
            None,
        )
        if (
            not peer_id
            or not verified_student(peer_id)
            or _is_blocked(user['_id'], peer_id)
        ):
            return None
    return chat


def chat_display_name(user_id, chat):
    if chat.get('kind') == 'group':
        return chat.get('name', 'Student group')
    current_oid = to_object_id(user_id)
    peer_id = next(
        (member_id for member_id in chat.get('member_ids', []) if member_id != current_oid),
        None,
    )
    peer = users().find_one({'_id': peer_id}) if peer_id else None
    return peer.get('full_name', 'LPU student') if peer else 'LPU student'


def list_messages(user_id, chat_id, after_id=None):
    chat = get_chat(user_id, chat_id)
    if not chat:
        raise SocialAccessError('This conversation is unavailable.')
    query = {'chat_id': chat['_id']}
    after_oid = to_object_id(after_id) if after_id else None
    if after_id and not after_oid:
        raise ValueError('The message cursor is invalid.')
    if after_oid:
        query['_id'] = {'$gt': after_oid}
        messages = list(social_messages().find(query).sort('_id', ASCENDING).limit(CHAT_HISTORY_LIMIT))
    else:
        messages = list(social_messages().find(query).sort('_id', DESCENDING).limit(CHAT_HISTORY_LIMIT))
        messages.reverse()
    for message in messages:
        message['id'] = str(message.pop('_id'))
        message['sender_id'] = str(message['sender_id'])
        message.pop('chat_id', None)
    return messages


def validate_external_media_url(media_url):
    parsed = urlparse(media_url.strip())
    suffix = unquote(parsed.path).lower().rsplit('.', 1)
    extension = f'.{suffix[-1]}' if len(suffix) == 2 else ''
    if (
        parsed.scheme != 'https'
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or extension not in IMAGE_SUFFIXES | VIDEO_SUFFIXES
    ):
        raise ValueError('Use a direct HTTPS image or video link ending in a supported file type.')
    hostname = parsed.hostname.lower()
    if hostname in {'localhost', 'localhost.localdomain'} or hostname.endswith('.local'):
        raise ValueError('Local and private-network media links are not allowed.')
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_reserved or address.is_unspecified
    ):
        raise ValueError('Local and private-network media links are not allowed.')
    return {
        'url': media_url.strip(),
        'media_type': 'image' if extension in IMAGE_SUFFIXES else 'video',
        'public_id': '',
    }


def send_message(user_id, chat_id, body='', gif_url='', media=None):
    author = _require_student(user_id)
    chat = get_chat(user_id, chat_id)
    if not chat:
        raise SocialAccessError('This conversation is unavailable.')
    if not isinstance(body, str) or not isinstance(gif_url, str):
        raise ValueError('Message content is invalid.')
    body = body.strip()
    gif_url = gif_url.strip()
    if media is not None and (
        not isinstance(media, dict)
        or not isinstance(media.get('url'), str)
        or media.get('media_type') not in {'image', 'video'}
    ):
        raise ValueError('The selected media is invalid.')
    if len(body) > 2000:
        raise ValueError('Messages must be 2,000 characters or fewer.')
    if sum(bool(value) for value in (gif_url, media)) > 1:
        raise ValueError('Send one GIF or image/video attachment at a time.')
    if not body and not gif_url and not media:
        raise ValueError('Write a message, choose a GIF, or attach image/video.')
    if gif_url:
        parsed = urlparse(gif_url)
        hostname = (parsed.hostname or '').lower()
        if (
            parsed.scheme != 'https'
            or not hostname.endswith('.giphy.com')
            or parsed.username
            or parsed.password
        ):
            raise ValueError('Choose a GIF from the GIPHY picker.')
    created_at = now()
    message = {
        'chat_id': chat['_id'],
        'sender_id': author['_id'],
        'sender_name': author.get('full_name', 'LPU student'),
        'body': body,
        'gif_url': gif_url,
        'media_url': media.get('url', '') if media else '',
        'media_type': media.get('media_type', '') if media else '',
        'media_public_id': media.get('public_id', '') if media else '',
        'created_at': created_at,
    }
    social_chats().update_one({'_id': chat['_id']}, {'$set': {'updated_at': created_at}})
    result = social_messages().insert_one(message)
    message['id'] = str(result.inserted_id)
    message['sender_id'] = str(message['sender_id'])
    message.pop('chat_id', None)
    return message


def start_video_call(user_id, chat_id):
    current = _require_student(user_id)
    chat = get_chat(user_id, chat_id)
    if not chat:
        raise SocialAccessError('This conversation is unavailable.')
    active_call = chat.get('active_call') or {}
    created_at = active_call.get('created_at')
    if (
        active_call.get('status') == 'active'
        and created_at
        and created_at + CALL_LIFETIME > now()
    ):
        return active_call
    call = {
        'id': uuid.uuid4().hex,
        'room_name': f'lpu-social-{chat["_id"]}-{uuid.uuid4().hex}',
        'status': 'active',
        'initiator_id': current['_id'],
        'initiator_name': current.get('full_name', 'LPU student'),
        'created_at': now(),
    }
    chat_oid = chat['_id']
    updated = social_chats().find_one_and_update(
        {
            '_id': chat_oid,
            'member_ids': current['_id'],
            '$or': [
                {'active_call.status': {'$ne': 'active'}},
                {'active_call': {'$exists': False}},
                {'active_call.created_at': {'$lte': call['created_at'] - CALL_LIFETIME}},
            ],
        },
        {'$set': {'active_call': call, 'updated_at': call['created_at']}},
        return_document=ReturnDocument.AFTER,
    )
    if updated:
        return updated['active_call']
    latest = social_chats().find_one({'_id': chat_oid, 'member_ids': current['_id']})
    active_call = (latest or {}).get('active_call') or {}
    if active_call.get('status') == 'active':
        return active_call
    raise SocialAccessError('A video call could not be started. Please try again.')


def get_active_video_call(user_id, chat_id, call_id=''):
    chat = get_chat(user_id, chat_id)
    if not chat:
        raise SocialAccessError('This conversation is unavailable.')
    call = chat.get('active_call') or {}
    if (
        call.get('status') != 'active'
        or not call.get('created_at')
        or call['created_at'] + CALL_LIFETIME <= now()
        or (call_id and call.get('id') != call_id)
    ):
        raise ValueError('There is no active video call in this conversation.')
    return chat, call


def end_video_call(user_id, chat_id, call_id):
    current = _require_student(user_id)
    chat, call = get_active_video_call(user_id, chat_id, call_id)
    is_owner = chat.get('owner_id') == current['_id']
    is_initiator = call.get('initiator_id') == current['_id']
    if chat.get('kind') == 'group' and not (is_owner or is_initiator):
        raise SocialAccessError('Only the call initiator or group owner can end this call.')
    result = social_chats().update_one(
        {
            '_id': chat['_id'],
            'member_ids': current['_id'],
            'active_call.id': call_id,
            'active_call.status': 'active',
        },
        {'$set': {
            'active_call.status': 'ended',
            'active_call.ended_at': now(),
            'updated_at': now(),
        }},
    )
    return bool(result.modified_count)


def delete_group(user_id, chat_id):
    owner = _require_student(user_id)
    chat_oid = to_object_id(chat_id)
    if not chat_oid:
        return False
    result = social_chats().delete_one({
        '_id': chat_oid,
        'kind': 'group',
        'owner_id': owner['_id'],
        'member_ids': owner['_id'],
    })
    if not result.deleted_count:
        return False
    social_messages().delete_many({'chat_id': chat_oid})
    return True


def set_block(user_id, peer_id, blocked):
    current = _require_student(user_id)
    peer = _require_student(peer_id)
    if current['_id'] == peer['_id']:
        raise ValueError('You cannot block your own account.')
    query = {'blocker_id': current['_id'], 'blocked_id': peer['_id']}
    if blocked:
        try:
            social_blocks().insert_one({**query, 'created_at': now()})
        except DuplicateKeyError:
            pass
        return True
    social_blocks().delete_one(query)
    return False


def set_follow(user_id, peer_id, following):
    current = _require_student(user_id)
    peer = _require_student(peer_id)
    if current['_id'] == peer['_id']:
        raise ValueError('You cannot follow yourself.')
    _require_unblocked(current['_id'], peer['_id'])
    query = {'follower_id': current['_id'], 'followed_id': peer['_id']}
    if following:
        try:
            social_follows().insert_one({**query, 'created_at': now()})
        except DuplicateKeyError:
            pass
        return True
    social_follows().delete_one(query)
    return False


def search_gifs(query, api_key):
    if not api_key:
        raise SocialAccessError('GIF search is not configured. Ask the administrator to add GIPHY_API_KEY.')
    response = requests.get(
        'https://api.giphy.com/v1/gifs/search',
        params={
            'api_key': api_key,
            'q': query.strip()[:100],
            'limit': 12,
            'rating': 'pg',
        },
        timeout=5,
    )
    response.raise_for_status()
    data = response.json().get('data')
    if not isinstance(data, list):
        raise ValueError('GIPHY returned an unexpected response.')
    results = []
    for item in data:
        images = item.get('images', {})
        original = images.get('fixed_width', {})
        preview = images.get('fixed_width_small', {})
        url = original.get('url')
        parsed_url = urlparse(url or '')
        if (
            parsed_url.scheme != 'https'
            or not parsed_url.hostname
            or not parsed_url.hostname.endswith('.giphy.com')
        ):
            continue
        results.append({
            'url': url,
            'preview_url': preview.get('url', url),
            'title': item.get('title', 'GIF')[:120],
        })
    return results
