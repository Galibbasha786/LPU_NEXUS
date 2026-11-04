import logging
import uuid
from datetime import datetime, timedelta
from functools import wraps

from asgiref.sync import async_to_sync
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from accounts.session import login_required_mongo, role_required
from core.mongo import live_streams

logger = logging.getLogger(__name__)
MAX_TITLE_LENGTH = 140
MAX_DESCRIPTION_LENGTH = 2000
ALLOWED_ROLES = {'student', 'staff', 'admin'}


class LiveKitShutdownError(Exception):
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


def _stream_payload(stream, can_end=False):
    created_at = stream.get('created_at')
    return {
        'id': str(stream['_id']),
        'title': stream['title'],
        'description': stream.get('description', ''),
        'host_name': stream.get('host_name', 'LPU Staff'),
        'created_at': created_at.isoformat() if created_at else '',
        'status': stream.get('status', 'live'),
        'can_end': can_end,
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
    except (api.TwirpError, aiohttp.ClientError, TimeoutError, ValueError) as error:
        raise LiveKitShutdownError('LiveKit could not close the room.') from error


@login_required_mongo
@role_required('student', 'staff', 'admin')
def live_news_page(request):
    return render(request, 'live_news/page.html', {
        'can_broadcast': request.session.get('lpu_user_role') == 'staff',
    })


@require_GET
@api_roles_required(*ALLOWED_ROLES)
def active_streams(request):
    role = request.session['lpu_user_role']
    statuses = ['live'] if role == 'student' else ['live', 'ending']
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
        _stream_payload(
            stream,
            can_end=role == 'admin' or (
                role == 'staff' and stream.get('host_id') == user_id
            ),
        )
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
    if not _livekit_configured():
        return JsonResponse({
            'error': 'Live video is not configured. Contact the administrator.'
        }, status=503)

    host_id = request.session['lpu_user_id']
    try:
        existing_stream = live_streams().find_one({
            'host_id': host_id,
            'status': {'$in': ['live', 'ending']},
        }, {'_id': 1})
    except PyMongoError:
        logger.exception('Could not check for an existing live news stream')
        return JsonResponse({'error': 'Could not start the live broadcast.'}, status=503)
    if existing_stream:
        return JsonResponse({
            'error': 'End your current broadcast before starting another one.'
        }, status=409)

    stream_id = ObjectId()
    stream = {
        '_id': stream_id,
        'title': title,
        'description': description,
        'room_name': f'lpu-live-{uuid.uuid4().hex}',
        'host_id': host_id,
        'host_name': request.session.get('lpu_user_name', 'LPU Staff'),
        'status': 'live',
        'created_at': datetime.utcnow(),
        'ended_at': None,
    }
    try:
        live_streams().insert_one(stream)
    except PyMongoError:
        logger.exception('Could not create live news stream')
        return JsonResponse({'error': 'Could not start the live broadcast.'}, status=503)
    return JsonResponse({'stream': _stream_payload(stream, can_end=True)}, status=201)


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

    is_host = role == 'staff' and stream.get('host_id') == user_id
    if role != 'student' and not is_host and role != 'admin':
        return JsonResponse({'error': 'You cannot join this broadcast.'}, status=403)
    if not _livekit_configured():
        return JsonResponse({
            'error': 'Live video is not configured. Contact the administrator.'
        }, status=503)

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
            .with_name(request.session.get('lpu_user_name') or 'LPU user')
            .with_ttl(timedelta(hours=1))
            .with_grants(api.VideoGrants(
                room_join=True,
                room=stream['room_name'],
                can_publish=is_host,
                can_subscribe=True,
                can_publish_data=False,
            ))
            .to_jwt()
        )
    except (ImportError, PyJWTError, ValueError, TypeError):
        logger.exception('Could not issue LiveKit token for live stream %s', stream_id)
        return JsonResponse({'error': 'Could not connect to live video.'}, status=503)

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

    query = {'_id': oid, 'status': {'$in': ['live', 'ending', 'ended']}}
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
