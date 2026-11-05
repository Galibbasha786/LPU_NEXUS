import logging
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone
from functools import wraps

from asgiref.sync import async_to_sync
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from accounts.session import login_required_mongo, role_required
from core.mongo import live_comments, live_participants, live_streams, student_profiles
from core.storage import (
    LiveNewsPosterStorageError,
    LiveNewsPosterValidationError,
    delete_live_news_poster,
    save_live_news_poster,
)
from core.utils import to_object_id

logger = logging.getLogger(__name__)
MAX_TITLE_LENGTH = 140
MAX_DESCRIPTION_LENGTH = 2000
MAX_COMMENT_LENGTH = 500
ALLOWED_ROLES = {'student', 'staff', 'admin'}
PARTICIPANT_ACTIVE_WINDOW = timedelta(seconds=60)


class LiveKitShutdownError(Exception):
    pass


class LiveKitModerationError(Exception):
    pass


def api_roles_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.session.get('lpu_user_id'):
                return JsonResponse({'error': 'Please log in to continue.'}, status=401)
            if request.session.get('lpu_user_role') not in allowed_roles:
                return JsonResponse({'error': 'You do not have permission to do that.'}, status=403)
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def _livekit_configured():
    return bool(
        getattr(settings, 'LIVEKIT_URL', '').strip()
        and getattr(settings, 'LIVEKIT_API_KEY', '').strip()
        and getattr(settings, 'LIVEKIT_API_SECRET', '').strip()
    )


def _stream_payload(stream, role='', user_id=''):
    created_at = stream.get('created_at')
    scheduled_at = stream.get('scheduled_at')
    status = stream.get('status', 'live')
    return {
        'id': str(stream['_id']),
        'title': stream['title'],
        'description': stream.get('description', ''),
        'poster_url': stream.get('poster_url', ''),
        'host_name': stream.get('host_name', 'LPU Staff'),
        'created_at': created_at.isoformat() if created_at else '',
        'scheduled_at': scheduled_at.isoformat() if scheduled_at else '',
        'status': status,
        'comments_enabled': stream.get('comments_enabled', True),
        'can_end': role == 'admin' or (
            role == 'staff' and stream.get('host_id') == user_id
        ),
        'can_start': (
            role == 'staff' and status == 'scheduled'
            and stream.get('host_id') == user_id
        ),
        'can_moderate': role == 'admin' or (
            role == 'staff' and stream.get('host_id') == user_id
        ),
    }


def _delete_livekit_room(room_name):
    try:
        import aiohttp
        from livekit import api
    except ImportError as error:
        raise LiveKitShutdownError(
            'Live video dependencies are missing. Install the project requirements.'
        ) from error

    async def delete_room():
        client = api.LiveKitAPI(
            settings.LIVEKIT_URL,
            settings.LIVEKIT_API_KEY,
            settings.LIVEKIT_API_SECRET,
        )
        try:
            await client.room.delete_room(api.DeleteRoomRequest(room=room_name))
        finally:
            await client.aclose()

    try:
        async_to_sync(delete_room)()
    except api.TwirpError as error:
        error_code = error.code.casefold().replace('-', '_')
        error_message = error.message.casefold()
        if error_code in {'not_found', 'room_not_found'} or (
            'room' in error_message and 'not found' in error_message
        ):
            logger.info('LiveKit room %s was already closed', room_name)
            return
        logger.exception(
            'LiveKit rejected room shutdown (code=%s, status=%s)',
            error.code, error.status,
        )
        raise LiveKitShutdownError(
            f'LiveKit rejected room shutdown (code: {error.code}, HTTP {error.status}). '
            'Check LIVEKIT_URL and the API key permissions.'
        ) from error
    except (aiohttp.ClientError, TimeoutError, ValueError, RuntimeError) as error:
        logger.exception('Could not reach LiveKit to close room %s', room_name)
        raise LiveKitShutdownError(
            'Could not reach LiveKit to close the room. Check LIVEKIT_URL and try again.'
        ) from error


def _remove_livekit_participant(room_name, identity):
    try:
        import aiohttp
        from livekit import api
    except ImportError as error:
        raise LiveKitModerationError(
            'Live video dependencies are missing. Install the project requirements.'
        ) from error

    async def remove_participant():
        client = api.LiveKitAPI(
            settings.LIVEKIT_URL,
            settings.LIVEKIT_API_KEY,
            settings.LIVEKIT_API_SECRET,
        )
        try:
            await client.room.remove_participant(
                api.RoomParticipantIdentity(room=room_name, identity=identity)
            )
        finally:
            await client.aclose()

    try:
        async_to_sync(remove_participant)()
    except (api.TwirpError, aiohttp.ClientError, TimeoutError, ValueError) as error:
        raise LiveKitModerationError('LiveKit could not remove that viewer.') from error


@login_required_mongo
@role_required('student', 'staff', 'admin')
def live_news_page(request):
    return render(request, 'live_news/page.html', {
        'can_broadcast': request.session.get('lpu_user_role') == 'staff',
    })


def _parse_stream_id(stream_id):
    try:
        return ObjectId(stream_id)
    except InvalidId:
        return None


def _active_participant(stream_id, user_id):
    return live_participants().find_one({
        'stream_id': stream_id,
        'user_id': user_id,
        'last_seen': {'$gte': datetime.utcnow() - PARTICIPANT_ACTIVE_WINDOW},
    })


@require_POST
@api_roles_required(*ALLOWED_ROLES)
def stream_heartbeat(request, stream_id):
    oid = _parse_stream_id(stream_id)
    if not oid:
        return JsonResponse({'error': 'Live broadcast not found.'}, status=404)
    try:
        stream = live_streams().find_one({'_id': oid, 'status': 'live'}, {'_id': 1})
        if not stream:
            return JsonResponse({'error': 'This broadcast has ended.'}, status=404)
        result = live_participants().update_one(
            {
                'stream_id': oid,
                'user_id': request.session['lpu_user_id'],
            },
            {'$set': {'last_seen': datetime.utcnow()}},
        )
    except PyMongoError:
        logger.exception('Could not update live news participant presence')
        return JsonResponse({'error': 'Live chat is temporarily unavailable.'}, status=503)
    if not result.matched_count:
        return JsonResponse({'error': 'Join the live broadcast before using chat.'}, status=403)
    return JsonResponse({'ok': True})


@require_POST
@api_roles_required(*ALLOWED_ROLES)
def leave_stream(request, stream_id):
    oid = _parse_stream_id(stream_id)
    if not oid:
        return JsonResponse({'error': 'Live broadcast not found.'}, status=404)
    try:
        live_participants().delete_one({
            'stream_id': oid,
            'user_id': request.session['lpu_user_id'],
        })
    except PyMongoError:
        logger.exception('Could not remove live news participant presence')
        return JsonResponse({'error': 'Could not leave live chat cleanly.'}, status=503)
    return JsonResponse({'ok': True})


def _can_manage_stream(stream, request):
    role = request.session['lpu_user_role']
    return role == 'admin' or (
        role == 'staff' and stream.get('host_id') == request.session['lpu_user_id']
    )


@require_GET
@api_roles_required('staff', 'admin')
def stream_participants(request, stream_id):
    oid = _parse_stream_id(stream_id)
    if not oid:
        return JsonResponse({'error': 'Live broadcast not found.'}, status=404)
    try:
        stream = live_streams().find_one({'_id': oid, 'status': 'live'})
        if not stream:
            return JsonResponse({'error': 'This broadcast is no longer live.'}, status=404)
        if not _can_manage_stream(stream, request):
            return JsonResponse({'error': 'Only the broadcast host can manage viewers.'}, status=403)
        participants = list(live_participants().find({
            'stream_id': oid,
            'role': 'student',
            'last_seen': {'$gte': datetime.utcnow() - PARTICIPANT_ACTIVE_WINDOW},
        }).sort('display_name', 1).limit(200))
    except PyMongoError:
        logger.exception('Could not load live broadcast viewers')
        return JsonResponse({'error': 'Could not load broadcast viewers.'}, status=503)
    return JsonResponse({'participants': [{
        'user_id': participant['user_id'],
        'display_name': participant.get('display_name', 'Student'),
    } for participant in participants]})


@require_POST
@api_roles_required('staff', 'admin')
def remove_participant(request, stream_id, participant_user_id):
    oid = _parse_stream_id(stream_id)
    if not oid:
        return JsonResponse({'error': 'Live broadcast not found.'}, status=404)
    try:
        stream = live_streams().find_one({'_id': oid, 'status': 'live'})
        if not stream:
            return JsonResponse({'error': 'This broadcast is no longer live.'}, status=404)
        if not _can_manage_stream(stream, request):
            return JsonResponse({'error': 'Only the broadcast host can remove viewers.'}, status=403)
        participant = live_participants().find_one({
            'stream_id': oid,
            'user_id': participant_user_id,
            'role': 'student',
            'last_seen': {'$gte': datetime.utcnow() - PARTICIPANT_ACTIVE_WINDOW},
        })
    except PyMongoError:
        logger.exception('Could not load viewer for removal from stream %s', stream_id)
        return JsonResponse({'error': 'Could not remove that viewer.'}, status=503)
    if not participant:
        return JsonResponse({'error': 'That student is no longer watching.'}, status=404)
    if not _livekit_configured():
        return JsonResponse({
            'error': 'Live video is not configured. Contact the administrator.'
        }, status=503)

    try:
        _remove_livekit_participant(stream['room_name'], participant['identity'])
    except LiveKitModerationError as error:
        logger.exception('Could not remove viewer from live stream %s', stream_id)
        return JsonResponse({'error': str(error)}, status=503)

    try:
        live_participants().delete_one({
            'stream_id': oid,
            'user_id': participant_user_id,
        })
        live_streams().update_one(
            {'_id': oid},
            {'$addToSet': {'kicked_user_ids': participant_user_id}},
        )
    except PyMongoError:
        logger.exception('Could not persist removal of viewer from stream %s', stream_id)
        return JsonResponse({
            'error': 'The viewer was disconnected, but access could not be revoked. Try again.'
        }, status=503)
    return JsonResponse({'ok': True})


@require_http_methods(['GET', 'POST'])
@api_roles_required(*ALLOWED_ROLES)
def stream_comments(request, stream_id):
    oid = _parse_stream_id(stream_id)
    if not oid:
        return JsonResponse({'error': 'Live broadcast not found.'}, status=404)
    user_id = request.session['lpu_user_id']
    try:
        stream = live_streams().find_one({'_id': oid, 'status': 'live'})
        participant = _active_participant(oid, user_id)
    except PyMongoError:
        logger.exception('Could not authorize live chat access')
        return JsonResponse({'error': 'Live chat is temporarily unavailable.'}, status=503)
    if not stream:
        return JsonResponse({'error': 'This broadcast has ended.'}, status=404)
    if not participant:
        return JsonResponse({'error': 'Join the live broadcast before using chat.'}, status=403)

    if request.method == 'POST':
        if not stream.get('comments_enabled', True):
            return JsonResponse({'error': 'Comments are turned off for this broadcast.'}, status=403)
        if request.POST.get('type', 'text') != 'text':
            return JsonResponse({
                'error': 'Only text comments are stored. Send reactions through the live player.'
            }, status=400)
        content = request.POST.get('content', '').strip()
        if not content or len(content) > MAX_COMMENT_LENGTH:
            return JsonResponse({
                'error': f'Comments must be 1 to {MAX_COMMENT_LENGTH} characters.'
            }, status=400)

        message = {
            'stream_id': oid,
            'user_id': user_id,
            'display_name': participant['display_name'],
            'type': 'text',
            'content': content,
            'created_at': datetime.utcnow(),
        }
        try:
            result = live_comments().insert_one(message)
        except PyMongoError:
            logger.exception('Could not save live chat message for stream %s', stream_id)
            return JsonResponse({'error': 'Your message could not be sent.'}, status=503)
        return JsonResponse({'message': {
            'id': str(result.inserted_id),
            'display_name': message['display_name'],
            'type': 'text',
            'content': message['content'],
            'created_at': message['created_at'].isoformat(),
        }}, status=201)

    after = request.GET.get('after')
    query = {'stream_id': oid}
    if after:
        cursor_id = _parse_stream_id(after)
        if not cursor_id:
            return JsonResponse({'error': 'Invalid message cursor.'}, status=400)
        query['_id'] = {'$gt': cursor_id}
    try:
        cursor = live_comments().find(query).sort('_id', -1 if not after else 1).limit(50)
        messages = list(cursor)
    except PyMongoError:
        logger.exception('Could not load live chat messages for stream %s', stream_id)
        return JsonResponse({'error': 'Live chat is temporarily unavailable.'}, status=503)
    if not after:
        messages.reverse()
    return JsonResponse({
        'comments_enabled': stream.get('comments_enabled', True),
        'comments': [
            {
                'id': str(message['_id']),
                'display_name': message.get('display_name', 'LPU user'),
                'type': 'text',
                'content': message.get('content', ''),
                'created_at': message['created_at'].isoformat(),
            }
            for message in messages
        ],
    })


@require_POST
@api_roles_required('staff', 'admin')
def moderate_comments(request, stream_id):
    oid = _parse_stream_id(stream_id)
    if not oid:
        return JsonResponse({'error': 'Live broadcast not found.'}, status=404)
    requested_state = request.POST.get('enabled', '')
    if requested_state not in {'true', 'false'}:
        return JsonResponse({'error': 'Choose whether comments should be on or off.'}, status=400)
    enabled = requested_state == 'true'
    try:
        stream = live_streams().find_one({
            '_id': oid,
            'status': {'$in': ['live', 'scheduled']},
        })
        if not stream:
            return JsonResponse({'error': 'This broadcast is no longer available.'}, status=404)
        if not _can_manage_stream(stream, request):
            return JsonResponse({'error': 'Only the broadcast host can manage comments.'}, status=403)
        result = live_streams().update_one(
            {'_id': oid, 'status': {'$in': ['live', 'scheduled']}},
            {'$set': {'comments_enabled': enabled}},
        )
    except PyMongoError:
        logger.exception('Could not update live chat moderation state')
        return JsonResponse({'error': 'Could not update comment settings.'}, status=503)
    if not result.matched_count:
        return JsonResponse({'error': 'This broadcast is no longer available.'}, status=404)
    return JsonResponse({'comments_enabled': enabled})


@require_GET
@api_roles_required(*ALLOWED_ROLES)
def active_streams(request):
    role = request.session['lpu_user_role']
    statuses = ['live', 'scheduled'] if role == 'student' else [
        'live', 'ending', 'scheduled',
    ]
    try:
        streams = list(
            live_streams().find({'status': {'$in': statuses}})
            .sort('created_at', -1).limit(30)
        )
    except PyMongoError:
        logger.exception('Could not load live news streams')
        return JsonResponse({'error': 'Live news is temporarily unavailable.'}, status=503)
    user_id = request.session['lpu_user_id']
    return JsonResponse({'streams': [
        _stream_payload(stream, role, user_id)
        for stream in streams
    ]})


@require_POST
@api_roles_required('staff')
def start_stream(request):
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    if not title or len(title) > MAX_TITLE_LENGTH:
        return JsonResponse({
            'error': f'Enter a title of 1 to {MAX_TITLE_LENGTH} characters.'
        }, status=400)
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return JsonResponse({
            'error': f'The description must be {MAX_DESCRIPTION_LENGTH} characters or fewer.'
        }, status=400)
    poster_file = request.FILES.get('poster')
    scheduled_at = None
    scheduled_input = request.POST.get('scheduled_at', '').strip()
    if scheduled_input:
        try:
            local_time = datetime.strptime(scheduled_input, '%Y-%m-%dT%H:%M')
            scheduled_at = timezone.make_aware(
                local_time, timezone.get_current_timezone(),
            ).astimezone(datetime_timezone.utc).replace(tzinfo=None)
        except ValueError:
            return JsonResponse({'error': 'Choose a valid broadcast date and time.'}, status=400)
        if scheduled_at <= datetime.utcnow():
            return JsonResponse({'error': 'Choose a future broadcast date and time.'}, status=400)

    if not scheduled_at and not _livekit_configured():
        return JsonResponse({
            'error': 'Live video is not configured. Contact the administrator.'
        }, status=503)

    host_id = request.session['lpu_user_id']
    try:
        existing_stream = live_streams().find_one({
            'host_id': host_id,
            'status': {'$in': ['live', 'ending', 'scheduled']},
        }, {'_id': 1})
    except PyMongoError:
        logger.exception('Could not check for an existing live news stream')
        return JsonResponse({'error': 'Could not start the live broadcast.'}, status=503)
    if existing_stream:
        return JsonResponse({
            'error': 'End your current broadcast before starting another one.'
        }, status=409)

    try:
        poster = save_live_news_poster(poster_file)
    except LiveNewsPosterValidationError as error:
        return JsonResponse({'error': str(error)}, status=400)
    except LiveNewsPosterStorageError as error:
        return JsonResponse({'error': str(error)}, status=503)

    status = 'scheduled' if scheduled_at else 'live'
    stream_id = ObjectId()
    stream = {
        '_id': stream_id,
        'title': title,
        'description': description,
        'poster_url': poster['url'] if poster else '',
        'poster_public_id': poster['public_id'] if poster else '',
        'room_name': f'lpu-live-{uuid.uuid4().hex}' if status == 'live' else '',
        'host_id': host_id,
        'host_name': request.session.get('lpu_user_name', 'LPU Staff'),
        'status': status,
        'comments_enabled': True,
        'scheduled_at': scheduled_at,
        'created_at': datetime.utcnow(),
        'started_at': datetime.utcnow() if status == 'live' else None,
        'ended_at': None,
    }
    try:
        live_streams().insert_one(stream)
    except PyMongoError:
        if poster:
            delete_live_news_poster(poster)
        logger.exception('Could not create live news stream')
        return JsonResponse({'error': 'Could not start the live broadcast.'}, status=503)
    return JsonResponse({
        'stream': _stream_payload(stream, 'staff', host_id),
    }, status=201)


@require_POST
@api_roles_required('staff')
def go_live_stream(request, stream_id):
    try:
        oid = ObjectId(stream_id)
    except InvalidId:
        return JsonResponse({'error': 'Scheduled broadcast not found.'}, status=404)
    if not _livekit_configured():
        return JsonResponse({
            'error': 'Live video is not configured. Contact the administrator.'
        }, status=503)

    try:
        stream = live_streams().find_one_and_update(
            {
                '_id': oid,
                'host_id': request.session['lpu_user_id'],
                'status': 'scheduled',
                'scheduled_at': {'$lte': datetime.utcnow()},
            },
            {'$set': {
                'status': 'live',
                'room_name': f'lpu-live-{uuid.uuid4().hex}',
                'started_at': datetime.utcnow(),
            }},
            return_document=True,
        )
    except PyMongoError:
        logger.exception('Could not start scheduled live news stream %s', stream_id)
        return JsonResponse({'error': 'Could not start the scheduled broadcast.'}, status=503)
    if not stream:
        return JsonResponse({
            'error': 'This scheduled broadcast is no longer available to you.'
        }, status=404)
    return JsonResponse({'stream': _stream_payload(
        stream, 'staff', request.session['lpu_user_id'],
    )})


@require_POST
@api_roles_required(*ALLOWED_ROLES)
def stream_token(request, stream_id):
    try:
        oid = ObjectId(stream_id)
    except InvalidId:
        return JsonResponse({'error': 'Live broadcast not found.'}, status=404)

    role = request.session['lpu_user_role']
    user_id = request.session['lpu_user_id']
    try:
        stream = live_streams().find_one({'_id': oid, 'status': 'live'})
    except PyMongoError:
        logger.exception('Could not load live news stream')
        return JsonResponse({'error': 'Live video is temporarily unavailable.'}, status=503)
    if not stream:
        return JsonResponse({'error': 'This broadcast has ended.'}, status=404)
    if user_id in stream.get('kicked_user_ids', []):
        return JsonResponse({
            'error': 'The broadcast host removed you from this live session.'
        }, status=403)

    is_host = role == 'staff' and stream.get('host_id') == user_id
    if role != 'student' and not is_host and role != 'admin':
        return JsonResponse({'error': 'You cannot join this broadcast.'}, status=403)
    if not _livekit_configured():
        return JsonResponse({
            'error': 'Live video is not configured. Contact the administrator.'
        }, status=503)

    display_name = request.session.get('lpu_user_name') or 'LPU user'
    try:
        if role == 'student':
            student_id = to_object_id(user_id)
            if student_id:
                profile = student_profiles().find_one(
                    {'user_id': student_id}, {'registration_number': 1},
                )
                display_name = (profile or {}).get('registration_number') or display_name
    except PyMongoError:
        logger.exception('Could not load live chat display identity for user %s', user_id)
        return JsonResponse({'error': 'Could not join live news right now.'}, status=503)

    try:
        from livekit import api
        from jwt.exceptions import PyJWTError
    except ImportError:
        logger.exception('LiveKit token dependencies are not installed')
        return JsonResponse({
            'error': 'Live video dependencies are missing. Install the project requirements.'
        }, status=503)

    try:
        identity = f'{user_id}-{uuid.uuid4().hex[:12]}'
        token = (
            api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_name(display_name)
            .with_ttl(timedelta(hours=1))
            .with_grants(api.VideoGrants(
                room_join=True,
                room=stream['room_name'],
                can_publish=is_host,
                can_subscribe=True,
                can_publish_data=True,
            ))
            .to_jwt()
        )
    except (ImportError, PyJWTError, ValueError, TypeError):
        logger.exception('Could not issue LiveKit token for live stream %s', stream_id)
        return JsonResponse({'error': 'Could not connect to live video.'}, status=503)

    try:
        live_participants().update_one(
            {'stream_id': oid, 'user_id': user_id},
            {'$set': {
                'identity': identity,
                'display_name': display_name,
                'role': role,
                'last_seen': datetime.utcnow(),
            }, '$setOnInsert': {'stream_id': oid, 'user_id': user_id}},
            upsert=True,
        )
    except PyMongoError:
        logger.exception('Could not register live news participant %s', user_id)
        return JsonResponse({'error': 'Could not join live news right now.'}, status=503)

    return JsonResponse({
        'url': settings.LIVEKIT_URL.strip(),
        'token': token,
        'is_host': is_host,
    })


@require_POST
@api_roles_required('staff', 'admin')
def end_stream(request, stream_id):
    try:
        oid = ObjectId(stream_id)
    except InvalidId:
        return JsonResponse({'error': 'Live broadcast not found.'}, status=404)

    query = {'_id': oid, 'status': {'$in': ['scheduled', 'live', 'ending', 'ended']}}
    if request.session['lpu_user_role'] != 'admin':
        query['host_id'] = request.session['lpu_user_id']
    try:
        stream = live_streams().find_one(query)
    except PyMongoError:
        logger.exception('Could not load live news stream %s', stream_id)
        return JsonResponse({'error': 'Could not end the live broadcast.'}, status=503)
    if not stream:
        return JsonResponse({
            'error': 'This broadcast is no longer live or you cannot end it.'
        }, status=404)
    if stream['status'] == 'ended':
        return JsonResponse({'ok': True})

    if stream['status'] == 'scheduled':
        try:
            live_streams().update_one(
                {'_id': oid, 'status': 'scheduled'},
                {'$set': {'status': 'ended', 'ended_at': datetime.utcnow()}},
            )
        except PyMongoError:
            logger.exception('Could not cancel scheduled live news stream %s', stream_id)
            return JsonResponse({'error': 'Could not cancel the scheduled broadcast.'}, status=503)
        return JsonResponse({'ok': True})

    if stream['status'] == 'live':
        try:
            live_streams().update_one(
                {'_id': oid, 'status': 'live'},
                {'$set': {'status': 'ending'}},
            )
        except PyMongoError:
            logger.exception('Could not begin ending live news stream %s', stream_id)
            return JsonResponse({'error': 'Could not end the live broadcast.'}, status=503)

    try:
        _delete_livekit_room(stream['room_name'])
    except LiveKitShutdownError as error:
        logger.exception('Could not close LiveKit room for stream %s', stream_id)
        return JsonResponse({
            'error': f'The broadcast is closing, but its video room could not be shut down: {error}'
        }, status=503)

    try:
        live_streams().update_one(
            {'_id': oid, 'status': 'ending'},
            {'$set': {'status': 'ended', 'ended_at': datetime.utcnow()}},
        )
    except PyMongoError:
        logger.exception('Could not finish ending live news stream %s', stream_id)
        return JsonResponse({
            'error': 'The video room is closed, but the broadcast status could not be updated.'
        }, status=503)
    return JsonResponse({'ok': True})
