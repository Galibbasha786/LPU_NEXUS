import logging
from functools import wraps
from datetime import timedelta
import uuid

import requests
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from accounts.session import get_current_user, login_required_mongo
from core.storage import (
    SocialMediaStorageError,
    SocialMediaValidationError,
    delete_social_media,
    save_social_media,
)
from core.utils import to_object_id

from . import services

logger = logging.getLogger(__name__)


def verified_student_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        try:
            user = get_current_user(request)
        except PyMongoError:
            logger.exception('Could not verify the Social Hub account')
            messages.error(request, 'Your student account could not be verified. Please try again.')
            return redirect('accounts:dashboard')
        if not user or user.get('role') != 'student':
            messages.error(request, 'Social Hub is available to verified LPU students only.')
            return redirect('accounts:dashboard')
        if (
            user.get('active', True) is False
            or user.get('id_verification_status', 'verified') != 'verified'
        ):
            messages.error(request, 'Social Hub is available after your student account is verified.')
            return redirect('accounts:verification_pending')
        request.social_user = user
        return view_func(request, *args, **kwargs)
    return wrapped


def _feed_context(user):
    return {
        'user': user,
        'posts': services.list_feed(user['id']),
        'stories': services.list_stories(user['id']),
    }


def _channel_group(chat_id):
    return f'social.chat.{chat_id}'


def _broadcast_chat_event(chat_id, payload):
    try:
        async_to_sync(get_channel_layer().group_send)(
            _channel_group(chat_id),
            {'type': 'chat.event', 'payload': payload},
        )
        return True
    except RedisError:
        logger.exception('Could not broadcast a Social Hub chat event')
        return False


def _livekit_configured():
    return bool(
        settings.LIVEKIT_URL
        and settings.LIVEKIT_API_KEY
        and settings.LIVEKIT_API_SECRET
    )


def _issue_video_call_token(user, call):
    try:
        from livekit import api
        from jwt.exceptions import PyJWTError
    except ImportError as error:
        logger.exception('LiveKit token dependencies are not installed')
        raise services.SocialAccessError(
            'Video calling dependencies are missing. Contact the administrator.'
        ) from error

    display_name = user.get('full_name', 'LPU student')
    identity = f"{user['id']}-{uuid.uuid4().hex[:12]}"
    try:
        token = (
            api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_name(display_name)
            .with_ttl(timedelta(hours=1))
            .with_grants(api.VideoGrants(
                room_join=True,
                room=call['room_name'],
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            ))
            .to_jwt()
        )
    except (ImportError, PyJWTError, ValueError, TypeError):
        logger.exception('Could not issue a Social Hub video-call token')
        raise services.SocialAccessError('Could not connect to video calling. Please try again.') from None
    return {
        'url': settings.LIVEKIT_URL,
        'token': token,
        'call_id': call['id'],
        'initiator_name': call.get('initiator_name', ''),
    }


@login_required_mongo
@verified_student_required
@require_http_methods(['GET', 'POST'])
def feed(request):
    user = request.social_user
    if request.method == 'POST':
        caption = (request.POST.get('caption') or '').strip()
        registration_numbers = [
            number
            for value in request.POST.getlist('tagged_students')
            for number in value.split(',')
        ]
        uploaded_file = request.FILES.get('media')
        if len(caption) > 2200:
            messages.error(request, 'Captions must be 2,200 characters or fewer.')
            return redirect('social:feed')
        if not caption and not uploaded_file:
            messages.error(request, 'Add a caption, an image, or a video to publish a post.')
            return redirect('social:feed')
        media = None
        try:
            tagged_user_ids = services.resolve_tagged_students(
                user['id'], registration_numbers,
            )
            media = save_social_media(uploaded_file)
            services.create_post(user, caption, media, tagged_user_ids)
        except (ValueError, SocialMediaValidationError, SocialMediaStorageError) as error:
            if media:
                delete_social_media(media)
            messages.error(request, str(error))
        except PyMongoError:
            if media:
                delete_social_media(media)
            logger.exception('Could not publish a Social Hub post')
            messages.error(request, 'Your post could not be saved. Please try again.')
        else:
            messages.success(request, 'Your post is live.')
            return redirect('social:feed')

    try:
        context = _feed_context(user)
    except services.SocialAccessError as error:
        messages.error(request, str(error))
        context = {'user': user, 'posts': [], 'stories': []}
    except PyMongoError:
        logger.exception('Could not load the Social Hub feed')
        messages.error(request, 'The Social Hub feed could not be loaded. Please try again.')
        context = {'user': user, 'posts': [], 'stories': []}
    return render(request, 'social/feed.html', context)


@login_required_mongo
@verified_student_required
@require_POST
def create_story(request):
    user = request.social_user
    caption = (request.POST.get('caption') or '').strip()
    uploaded_file = request.FILES.get('media')
    if len(caption) > 500:
        messages.error(request, 'Story captions must be 500 characters or fewer.')
        return redirect('social:feed')
    if not uploaded_file:
        messages.error(request, 'Choose an image or video for your 24-hour story.')
        return redirect('social:feed')
    media = None
    try:
        media = save_social_media(uploaded_file)
        services.create_story(user, caption, media)
    except (ValueError, SocialMediaValidationError, SocialMediaStorageError) as error:
        if media:
            delete_social_media(media)
        messages.error(request, str(error))
    except PyMongoError:
        if media:
            delete_social_media(media)
        logger.exception('Could not create a Social Hub story')
        messages.error(request, 'Your story could not be saved. Please try again.')
    else:
        messages.success(request, 'Your story will be available for 24 hours.')
    return redirect('social:feed')


@login_required_mongo
@verified_student_required
@require_http_methods(['GET'])
def post_detail(request, post_id):
    try:
        posts = services.list_feed(request.social_user['id'], post_id=post_id)
    except services.SocialAccessError as error:
        messages.error(request, str(error))
        return redirect('social:feed')
    except PyMongoError:
        logger.exception('Could not load a Social Hub post')
        messages.error(request, 'The post could not be loaded. Please try again.')
        return redirect('social:feed')
    if not posts:
        messages.error(request, 'That post is unavailable.')
        return redirect('social:feed')
    return render(request, 'social/post.html', {
        'user': request.social_user,
        'post': posts[0],
    })


@login_required_mongo
@verified_student_required
@require_POST
def like_post(request, post_id):
    try:
        liked = services.toggle_like(request.social_user['id'], post_id)
    except (ValueError, services.SocialAccessError) as error:
        messages.error(request, str(error))
    except PyMongoError:
        logger.exception('Could not update a Social Hub like')
        messages.error(request, 'Your like could not be updated. Please try again.')
    else:
        messages.success(request, 'Post liked.' if liked else 'Like removed.')
    return redirect('social:feed')


@login_required_mongo
@verified_student_required
@require_POST
def comment_post(request, post_id):
    body = (request.POST.get('body') or '').strip()
    if not body or len(body) > 2000:
        messages.error(request, 'Enter a comment of up to 2,000 characters.')
    else:
        try:
            services.add_comment(request.social_user, post_id, body)
        except (ValueError, services.SocialAccessError) as error:
            messages.error(request, str(error))
        except PyMongoError:
            logger.exception('Could not add a Social Hub comment')
            messages.error(request, 'Your comment could not be saved. Please try again.')
        else:
            messages.success(request, 'Your comment was added.')
    return redirect('social:feed')


@login_required_mongo
@verified_student_required
@require_POST
def reshare_post(request, post_id):
    caption = (request.POST.get('caption') or '').strip()
    if len(caption) > 500:
        messages.error(request, 'Reshare captions must be 500 characters or fewer.')
    else:
        try:
            services.create_reshare(request.social_user, post_id, caption)
        except (ValueError, services.SocialAccessError) as error:
            messages.error(request, str(error))
        except PyMongoError:
            logger.exception('Could not reshare a Social Hub post')
            messages.error(request, 'The post could not be reshared. Please try again.')
        else:
            messages.success(request, 'Post reshared to your feed.')
    return redirect('social:feed')


@login_required_mongo
@verified_student_required
@require_POST
def share_post(request, post_id):
    peer_id = request.POST.get('peer_id', '')
    try:
        chat, message = services.share_post_in_direct_chat(
            request.social_user['id'], post_id, peer_id,
        )
    except (ValueError, services.SocialAccessError) as error:
        return JsonResponse({'error': str(error)}, status=400)
    except PyMongoError:
        logger.exception('Could not share a Social Hub post in a direct chat')
        return JsonResponse({'error': 'The post could not be shared. Please try again.'}, status=503)

    realtime = _broadcast_chat_event(str(chat['_id']), {
        'type': 'message',
        'id': message['id'],
        'sender_id': message['sender_id'],
        'sender_name': message['sender_name'],
        'body': '',
        'gif_url': '',
        'media_url': '',
        'media_type': '',
        'shared_post': message['shared_post'],
        'created_at': message['created_at'].isoformat(),
    })
    return JsonResponse({
        'url': reverse('social:chat', kwargs={'chat_id': str(chat['_id'])}),
        'realtime': realtime,
    })


@login_required_mongo
@verified_student_required
@require_http_methods(['GET'])
def people(request):
    query = (request.GET.get('q') or '').strip()[:30]
    try:
        students = (
            services.search_students_for_tag(request.social_user['id'], query)
            if query else services.students_for_people(request.social_user['id'])
        )
        if query:
            states = {student['id']: student for student in services.students_for_people(request.social_user['id'], limit=200)}
            for student in students:
                student.update({key: states.get(student['id'], {}).get(key) for key in ('blocked_by_me', 'blocked_me', 'following')})
    except services.SocialAccessError as error:
        messages.error(request, str(error))
        students = []
    except PyMongoError:
        logger.exception('Could not load verified students for Social Hub')
        messages.error(request, 'The student list could not be loaded. Please try again.')
        students = []
    return render(request, 'social/people.html', {
        'user': request.social_user,
        'students': students,
        'search_query': query,
    })


@login_required_mongo
@verified_student_required
@require_http_methods(['GET'])
def student_profile(request, peer_id):
    try:
        profile = services.student_profile(request.social_user['id'], peer_id)
    except (ValueError, services.SocialAccessError):
        messages.error(request, 'That student profile is unavailable.')
        return redirect('social:people')
    except PyMongoError:
        logger.exception('Could not load a Social Hub student profile')
        messages.error(request, 'The student profile could not be loaded. Please try again.')
        return redirect('social:people')
    return render(request, 'social/student_profile.html', {
        'user': request.social_user,
        'profile': profile,
    })


@login_required_mongo
@verified_student_required
@require_http_methods(['GET'])
def search_students(request):
    query = (request.GET.get('q') or '').strip()
    if not query:
        return JsonResponse({'results': []})
    try:
        results = services.search_students_for_tag(
            request.social_user['id'], query,
        )
    except services.SocialAccessError as error:
        return JsonResponse({'error': str(error)}, status=403)
    except PyMongoError:
        logger.exception('Could not search verified Social Hub students')
        return JsonResponse({'error': 'Student search is temporarily unavailable.'}, status=503)
    return JsonResponse({'results': results})


@login_required_mongo
@verified_student_required
@require_POST
def set_student_block(request, peer_id):
    blocked = request.POST.get('blocked') == 'true'
    try:
        services.set_block(request.social_user['id'], peer_id, blocked)
    except (ValueError, services.SocialAccessError) as error:
        messages.error(request, str(error))
    except PyMongoError:
        logger.exception('Could not update a Social Hub block')
        messages.error(request, 'The block setting could not be updated. Please try again.')
    else:
        messages.success(
            request,
            'Student blocked.' if blocked else 'Student unblocked.',
        )
    return redirect('social:people')


@login_required_mongo
@verified_student_required
@require_POST
def set_student_follow(request, peer_id):
    following = request.POST.get('following') == 'true'
    try:
        services.set_follow(request.social_user['id'], peer_id, following)
    except (ValueError, services.SocialAccessError) as error:
        messages.error(request, str(error))
    except PyMongoError:
        logger.exception('Could not update a Social Hub follow')
        messages.error(request, 'The follow setting could not be updated. Please try again.')
    else:
        messages.success(request, 'Student followed.' if following else 'Student unfollowed.')
    return_to = request.POST.get('return_to', '')
    if return_to and url_has_allowed_host_and_scheme(
        return_to, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(return_to)
    return redirect('social:people')


@login_required_mongo
@verified_student_required
@require_http_methods(['GET', 'POST'])
def chats(request):
    user = request.social_user
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        member_ids = request.POST.getlist('members')
        if not name or len(name) > 80:
            messages.error(request, 'Enter a group name of up to 80 characters.')
        else:
            try:
                group = services.create_group(user['id'], name, member_ids)
            except (ValueError, services.SocialAccessError) as error:
                messages.error(request, str(error))
            except PyMongoError:
                logger.exception('Could not create a Social Hub group')
                messages.error(request, 'The group could not be created. Please try again.')
            else:
                messages.success(request, 'Group chat created.')
                return redirect('social:chat', chat_id=str(group['_id']))
    try:
        chat_list = services.list_chats(user['id'])
        students = services.students_for_people(user['id'])
    except services.SocialAccessError as error:
        messages.error(request, str(error))
        chat_list, students = [], []
    except PyMongoError:
        logger.exception('Could not load Social Hub conversations')
        messages.error(request, 'Your conversations could not be loaded. Please try again.')
        chat_list, students = [], []
    return render(request, 'social/chats.html', {
        'user': user,
        'chats': chat_list,
        'students': students,
    })


@login_required_mongo
@verified_student_required
@require_POST
def start_direct_chat(request):
    try:
        peer_id = request.POST.get('peer_id', '')
        registration_number = request.POST.get('registration_number', '')
        if registration_number:
            peer = services.student_for_registration(
                request.social_user['id'], registration_number,
            )
            peer_id = str(peer['_id'])
        chat = services.create_direct_chat(request.social_user['id'], peer_id)
    except (ValueError, services.SocialAccessError) as error:
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'error': str(error)}, status=400)
        messages.error(request, str(error))
        return redirect('social:people')
    except PyMongoError:
        logger.exception('Could not start a direct Social Hub chat')
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'error': 'The conversation could not be started.'}, status=503)
        messages.error(request, 'The conversation could not be started. Please try again.')
        return redirect('social:people')
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'url': reverse('social:chat', kwargs={'chat_id': str(chat['_id'])}),
        })
    return redirect('social:chat', chat_id=str(chat['_id']))


@login_required_mongo
@verified_student_required
@require_http_methods(['GET'])
def chat_detail(request, chat_id):
    user = request.social_user
    try:
        chat = services.get_chat(user['id'], chat_id)
        if not chat:
            messages.error(request, 'This conversation is unavailable.')
            return redirect('social:chats')
        chat['id'] = str(chat['_id'])
        chat['display_name'] = services.chat_display_name(user['id'], chat)
        chat['is_owner'] = str(chat.get('owner_id')) == user['id']
        chat['messages'] = services.list_messages(user['id'], chat_id)
        chat['last_message_id'] = chat['messages'][-1]['id'] if chat['messages'] else ''
        active_call = chat.get('active_call') or {}
        chat['active_call'] = (
            active_call
            if active_call.get('status') == 'active'
            and active_call.get('created_at')
            and active_call['created_at'] + services.CALL_LIFETIME > services.now()
            else None
        )
        chat['can_end_call'] = bool(
            chat['active_call']
            and (
                chat['active_call'].get('initiator_id') == to_object_id(user['id'])
                or (
                    chat.get('kind') == 'group'
                    and chat.get('owner_id') == to_object_id(user['id'])
                )
            )
        )
    except PyMongoError:
        logger.exception('Could not load a Social Hub conversation')
        messages.error(request, 'The conversation could not be loaded. Please try again.')
        return redirect('social:chats')
    except services.SocialAccessError as error:
        messages.error(request, str(error))
        return redirect('social:chats')
    return render(request, 'social/chat.html', {
        'user': user,
        'chat': chat,
        'send_url': reverse('social:send_message', kwargs={'chat_id': chat_id}),
        'messages_url': reverse('social:messages', kwargs={'chat_id': chat_id}),
        'gif_search_url': reverse('social:gif_search'),
        'delete_url': reverse('social:delete_group', kwargs={'chat_id': chat_id}),
        'direct_chat_url': reverse('social:start_direct'),
        'start_call_url': reverse('social:start_call', kwargs={'chat_id': chat_id}),
        'join_call_url': reverse('social:join_call', kwargs={'chat_id': chat_id}),
        'end_call_url': reverse('social:end_call', kwargs={'chat_id': chat_id}),
        'call_status_url': reverse('social:call_status', kwargs={'chat_id': chat_id}),
        'livekit_configured': _livekit_configured(),
        'chat_ws_path': f'/ws/social/chats/{chat_id}/',
    })


@login_required_mongo
@verified_student_required
@require_http_methods(['GET'])
def messages_json(request, chat_id):
    try:
        messages_list = services.list_messages(
            request.social_user['id'],
            chat_id,
            request.GET.get('after'),
        )
    except (ValueError, services.SocialAccessError) as error:
        return JsonResponse({'error': str(error)}, status=403)
    except PyMongoError:
        logger.exception('Could not refresh a Social Hub conversation')
        return JsonResponse({'error': 'Messages could not be loaded.'}, status=503)
    return JsonResponse({'messages': messages_list})


@login_required_mongo
@verified_student_required
@require_POST
def send_chat_message(request, chat_id):
    uploaded_file = request.FILES.get('media')
    media_url = (request.POST.get('media_url') or '').strip()
    gif_url = (request.POST.get('gif_url') or '').strip()
    media = None
    if uploaded_file and media_url:
        error = 'Choose an upload or a direct media link, not both.'
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'error': error}, status=400)
        messages.error(request, error)
        return redirect('social:chat', chat_id=chat_id)
    if (uploaded_file or media_url) and gif_url:
        error = 'Send either a GIF or an image/video attachment, not both.'
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'error': error}, status=400)
        messages.error(request, error)
        return redirect('social:chat', chat_id=chat_id)

    try:
        if uploaded_file:
            media = save_social_media(uploaded_file)
        elif media_url:
            media = services.validate_external_media_url(media_url)
        message = services.send_message(
            request.social_user['id'],
            chat_id,
            request.POST.get('body', ''),
            gif_url,
            media,
        )
    except (ValueError, services.SocialAccessError) as error:
        if media and uploaded_file:
            delete_social_media(media)
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'error': str(error)}, status=400)
        messages.error(request, str(error))
    except (SocialMediaStorageError, SocialMediaValidationError) as error:
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'error': str(error)}, status=400)
        messages.error(request, str(error))
    except PyMongoError:
        if media and uploaded_file:
            delete_social_media(media)
        logger.exception('Could not send a Social Hub message')
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'error': 'Your message could not be sent.'}, status=503)
        messages.error(request, 'Your message could not be sent. Please try again.')
    else:
        realtime = _broadcast_chat_event(
            chat_id,
            {
                'type': 'message',
                'id': message['id'],
                'sender_id': message['sender_id'],
                'sender_name': message['sender_name'],
                'body': message.get('body', ''),
                'gif_url': message.get('gif_url', ''),
                'media_url': message.get('media_url', ''),
                'media_type': message.get('media_type', ''),
                'shared_post': message.get('shared_post'),
                'created_at': message['created_at'].isoformat(),
            },
        )
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'message': message, 'realtime': realtime})
        return redirect('social:chat', chat_id=chat_id)
    return redirect('social:chat', chat_id=chat_id)


@login_required_mongo
@verified_student_required
@require_POST
def start_video_call(request, chat_id):
    if not _livekit_configured():
        return JsonResponse({
            'error': 'Video calling is not configured. Contact the administrator.'
        }, status=503)
    try:
        call = services.start_video_call(request.social_user['id'], chat_id)
        connection = _issue_video_call_token(request.social_user, call)
    except services.SocialAccessError as error:
        return JsonResponse({'error': str(error)}, status=403)
    except PyMongoError:
        logger.exception('Could not start a Social Hub video call')
        return JsonResponse({'error': 'The video call could not be started.'}, status=503)
    _broadcast_chat_event(chat_id, {
        'type': 'call.started',
        'call_id': call['id'],
        'initiator_name': call.get('initiator_name', ''),
        'initiator_id': str(call.get('initiator_id', '')),
    })
    return JsonResponse(connection)


@login_required_mongo
@verified_student_required
@require_POST
def join_video_call(request, chat_id):
    if not _livekit_configured():
        return JsonResponse({
            'error': 'Video calling is not configured. Contact the administrator.'
        }, status=503)
    call_id = request.POST.get('call_id', '')
    try:
        _, call = services.get_active_video_call(
            request.social_user['id'], chat_id, call_id,
        )
        connection = _issue_video_call_token(request.social_user, call)
    except (ValueError, services.SocialAccessError) as error:
        return JsonResponse({'error': str(error)}, status=403)
    except PyMongoError:
        logger.exception('Could not join a Social Hub video call')
        return JsonResponse({'error': 'The video call could not be joined.'}, status=503)
    return JsonResponse(connection)


@login_required_mongo
@verified_student_required
@require_http_methods(['GET'])
def call_status(request, chat_id):
    try:
        chat = services.get_chat(request.social_user['id'], chat_id)
        if not chat:
            return JsonResponse({'error': 'This conversation is unavailable.'}, status=403)
        call = chat.get('active_call') or {}
        if (
            call.get('status') != 'active'
            or not call.get('created_at')
            or call['created_at'] + services.CALL_LIFETIME <= services.now()
        ):
            return JsonResponse({'active': False})
    except services.SocialAccessError as error:
        return JsonResponse({'error': str(error)}, status=403)
    except PyMongoError:
        logger.exception('Could not check the Social Hub call status')
        return JsonResponse({'error': 'Call status is temporarily unavailable.'}, status=503)
    return JsonResponse({
        'active': True,
        'call_id': call['id'],
        'initiator_name': call.get('initiator_name', 'LPU student'),
    })


@login_required_mongo
@verified_student_required
@require_POST
def end_video_call(request, chat_id):
    call_id = request.POST.get('call_id', '')
    try:
        ended = services.end_video_call(
            request.social_user['id'], chat_id, call_id,
        )
    except (ValueError, services.SocialAccessError) as error:
        return JsonResponse({'error': str(error)}, status=403)
    except PyMongoError:
        logger.exception('Could not end a Social Hub video call')
        return JsonResponse({'error': 'The video call could not be ended.'}, status=503)
    if ended:
        _broadcast_chat_event(chat_id, {
            'type': 'call.ended',
            'call_id': call_id,
        })
    return JsonResponse({'ended': ended})


@login_required_mongo
@verified_student_required
@require_POST
def delete_chat_group(request, chat_id):
    try:
        deleted = services.delete_group(request.social_user['id'], chat_id)
    except (ValueError, services.SocialAccessError) as error:
        messages.error(request, str(error))
    except PyMongoError:
        logger.exception('Could not delete a Social Hub group')
        messages.error(request, 'The group could not be deleted. Please try again.')
    else:
        if deleted:
            messages.success(request, 'Group and its messages deleted.')
            return redirect('social:chats')
        messages.error(request, 'Only the group creator can delete this group.')
    return redirect('social:chat', chat_id=chat_id)


@login_required_mongo
@verified_student_required
@require_http_methods(['GET'])
def gif_search(request):
    query = (request.GET.get('q') or '').strip()
    if not query:
        return JsonResponse({'error': 'Enter a search term.'}, status=400)
    try:
        results = services.search_gifs(query, settings.GIPHY_API_KEY)
    except services.SocialAccessError as error:
        return JsonResponse({'error': str(error)}, status=503)
    except (requests.RequestException, ValueError):
        logger.exception('GIPHY search failed')
        return JsonResponse({'error': 'GIF search is temporarily unavailable.'}, status=502)
    return JsonResponse({'results': results})
