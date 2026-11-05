import builtins
from datetime import timedelta
from unittest.mock import patch

from bson import ObjectId
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from livekit import api
import jwt

from .views import LiveKitShutdownError, _delete_livekit_room


class LiveNewsViewTests(TestCase):
    def setUp(self):
        self.stream_id = ObjectId()
        self.live_stream = {
            '_id': self.stream_id,
            'title': 'Campus update',
            'description': 'Important news',
            'room_name': 'private-live-room',
            'host_id': 'staff-1',
            'host_name': 'Staff Member',
            'status': 'live',
        }

    def login_as(self, role, user_id='staff-1', name='Staff Member'):
        session = self.client.session
        session['lpu_user_id'] = user_id
        session['lpu_user_role'] = role
        session['lpu_user_name'] = name
        session.save()

    @patch('live_news.views.async_to_sync')
    def test_shutdown_treats_already_missing_livekit_room_as_closed(self, async_to_sync):
        async_to_sync.return_value.side_effect = api.TwirpError(
            'not_found', 'room not found', status=404,
        )

        _delete_livekit_room('already-closed-room')

    @patch('live_news.views.async_to_sync')
    def test_shutdown_reports_livekit_permission_errors(self, async_to_sync):
        async_to_sync.return_value.side_effect = api.TwirpError(
            'permission_denied', 'not allowed', status=403,
        )

        with self.assertRaisesMessage(
            LiveKitShutdownError, 'code: permission_denied, HTTP 403'
        ):
            _delete_livekit_room('private-live-room')

    def test_staff_page_renders_broadcast_controls(self):
        self.login_as('staff')

        response = self.client.get('/live-news/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Broadcast or schedule campus news')
        self.assertContains(response, 'Flip camera')
        self.assertContains(response, 'livekit-client@2')

    @patch('live_news.views.live_streams')
    def test_student_sees_active_stream_without_room_credentials(self, live_streams):
        self.login_as('student', 'student-1', 'Student')
        collection = live_streams.return_value
        stream = {
            **self.live_stream,
            'poster_url': 'https://res.cloudinary.com/test/live-news/poster.png',
        }
        collection.find.return_value.sort.return_value.limit.return_value = [stream]

        response = self.client.get('/live-news/api/streams/')

        self.assertEqual(response.status_code, 200)
        stream = response.json()['streams'][0]
        self.assertEqual(stream['title'], 'Campus update')
        self.assertEqual(
            stream['poster_url'],
            'https://res.cloudinary.com/test/live-news/poster.png',
        )
        self.assertNotIn('room_name', stream)
        self.assertNotIn('host_id', stream)
        self.assertFalse(stream['can_end'])

    @override_settings(
        LIVEKIT_URL='wss://live.example',
        LIVEKIT_API_KEY='test-key',
        LIVEKIT_API_SECRET='test-secret',
    )
    @patch('live_news.views.live_streams')
    def test_staff_can_start_a_broadcast(self, live_streams):
        self.login_as('staff')
        live_streams.return_value.find_one.return_value = None

        response = self.client.post('/live-news/api/start/', {
            'title': '  Campus update  ',
            'description': '  Important news  ',
        })

        self.assertEqual(response.status_code, 201)
        saved = live_streams.return_value.insert_one.call_args.args[0]
        self.assertEqual(saved['title'], 'Campus update')
        self.assertEqual(saved['description'], 'Important news')
        self.assertEqual(saved['status'], 'live')
        self.assertTrue(response.json()['stream']['can_end'])

    @override_settings(
        LIVEKIT_URL='wss://live.example',
        LIVEKIT_API_KEY='test-key',
        LIVEKIT_API_SECRET='test-secret',
    )
    @patch('live_news.views.live_streams')
    def test_staff_must_end_existing_broadcast_before_starting_another(self, live_streams):
        self.login_as('staff')
        live_streams.return_value.find_one.return_value = {'_id': ObjectId()}

        response = self.client.post('/live-news/api/start/', {'title': 'Another update'})

        self.assertEqual(response.status_code, 409)
        live_streams.return_value.insert_one.assert_not_called()

    @override_settings(LIVEKIT_URL='', LIVEKIT_API_KEY='', LIVEKIT_API_SECRET='')
    @patch('live_news.views.live_streams')
    def test_broadcast_cannot_start_without_sfu_configuration(self, live_streams):
        self.login_as('staff')

        response = self.client.post('/live-news/api/start/', {'title': 'Campus update'})

        self.assertEqual(response.status_code, 503)
        live_streams.return_value.insert_one.assert_not_called()

    @patch('live_news.views.live_streams')
    def test_student_cannot_start_a_broadcast(self, live_streams):
        self.login_as('student', 'student-1', 'Student')

        response = self.client.post('/live-news/api/start/', {'title': 'Campus update'})

        self.assertEqual(response.status_code, 403)
        live_streams.return_value.insert_one.assert_not_called()

    @override_settings(
        LIVEKIT_URL='wss://live.example',
        LIVEKIT_API_KEY='test-key',
        LIVEKIT_API_SECRET='test-secret-that-is-long-enough-for-hs256',
    )
    @patch('live_news.views.live_participants')
    @patch('live_news.views.student_profiles')
    @patch('live_news.views.live_streams')
    def test_student_token_can_subscribe_but_cannot_publish(
        self, live_streams, student_profiles, live_participants
    ):
        self.login_as('student', 'student-1', 'Student')
        live_streams.return_value.find_one.return_value = self.live_stream
        student_profiles.return_value.find_one.return_value = {
            'registration_number': '12345678',
        }

        response = self.client.post(f'/live-news/api/{self.stream_id}/token/')

        self.assertEqual(response.status_code, 200)
        claims = jwt.decode(
            response.json()['token'],
            'test-secret-that-is-long-enough-for-hs256',
            algorithms=['HS256'],
        )
        self.assertEqual(claims['video']['room'], 'private-live-room')
        self.assertFalse(claims['video']['canPublish'])
        self.assertTrue(claims['video']['canSubscribe'])

    @override_settings(
        LIVEKIT_URL='wss://live.example',
        LIVEKIT_API_KEY='test-key',
        LIVEKIT_API_SECRET='test-secret-that-is-long-enough-for-hs256',
    )
    @patch('live_news.views.live_participants')
    @patch('live_news.views.live_streams')
    def test_only_the_stream_owner_gets_a_publishing_token(
        self, live_streams, live_participants
    ):
        self.login_as('staff')
        live_streams.return_value.find_one.return_value = self.live_stream

        response = self.client.post(f'/live-news/api/{self.stream_id}/token/')

        self.assertEqual(response.status_code, 200)
        claims = jwt.decode(
            response.json()['token'],
            'test-secret-that-is-long-enough-for-hs256',
            algorithms=['HS256'],
        )
        self.assertTrue(claims['video']['canPublish'])

    @override_settings(
        LIVEKIT_URL='wss://live.example',
        LIVEKIT_API_KEY='test-key',
        LIVEKIT_API_SECRET='test-secret',
    )
    @patch('live_news.views.student_profiles')
    @patch('live_news.views.live_streams')
    def test_missing_jwt_dependency_returns_actionable_error(
        self, live_streams, student_profiles
    ):
        self.login_as('student', 'student-1', 'Student')
        live_streams.return_value.find_one.return_value = self.live_stream
        student_profiles.return_value.find_one.return_value = {
            'registration_number': '12345678',
        }
        original_import = builtins.__import__

        def import_without_jwt(name, *args, **kwargs):
            if name == 'jwt.exceptions':
                raise ModuleNotFoundError("No module named 'jwt'")
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=import_without_jwt):
            response = self.client.post(f'/live-news/api/{self.stream_id}/token/')

        self.assertEqual(response.status_code, 503)
        self.assertIn('Install the project requirements', response.json()['error'])

    @patch('live_news.views.live_streams')
    @patch('live_news.views._delete_livekit_room')
    def test_staff_can_end_only_their_own_broadcast(self, delete_room, live_streams):
        self.login_as('staff', 'staff-2', 'Another staff member')
        live_streams.return_value.find_one.return_value = None

        response = self.client.post(f'/live-news/api/{self.stream_id}/end/')

        self.assertEqual(response.status_code, 404)
        query = live_streams.return_value.find_one.call_args.args[0]
        self.assertEqual(query['host_id'], 'staff-2')
        delete_room.assert_not_called()

    @patch('live_news.views.live_streams')
    @patch('live_news.views._delete_livekit_room')
    def test_ending_broadcast_deletes_room_before_marking_ended(
        self, delete_room, live_streams
    ):
        self.login_as('staff')
        collection = live_streams.return_value
        collection.find_one.return_value = self.live_stream

        response = self.client.post(f'/live-news/api/{self.stream_id}/end/')

        self.assertEqual(response.status_code, 200)
        delete_room.assert_called_once_with('private-live-room')
        self.assertEqual(
            collection.update_one.call_args_list[0].args[1]['$set']['status'],
            'ending',
        )
        self.assertEqual(
            collection.update_one.call_args_list[1].args[1]['$set']['status'],
            'ended',
        )

    @patch('live_news.views.live_streams')
    def test_missing_aiohttp_does_not_break_server_and_returns_actionable_error(
        self, live_streams
    ):
        self.login_as('staff')
        live_streams.return_value.find_one.return_value = self.live_stream
        original_import = builtins.__import__

        def import_without_aiohttp(name, *args, **kwargs):
            if name == 'aiohttp':
                raise ModuleNotFoundError("No module named 'aiohttp'")
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=import_without_aiohttp):
            response = self.client.post(f'/live-news/api/{self.stream_id}/end/')

        self.assertEqual(response.status_code, 503)
        self.assertIn('Install the project requirements', response.json()['error'])

    @patch('live_news.views.live_streams')
    def test_staff_can_schedule_a_future_broadcast(self, live_streams):
        self.login_as('staff')
        live_streams.return_value.find_one.return_value = None
        scheduled_at = timezone.localtime(
            timezone.now() + timedelta(days=1)
        ).strftime('%Y-%m-%dT%H:%M')

        response = self.client.post('/live-news/api/start/', {
            'title': 'Tomorrow update',
            'scheduled_at': scheduled_at,
        })

        self.assertEqual(response.status_code, 201)
        saved = live_streams.return_value.insert_one.call_args.args[0]
        self.assertEqual(saved['status'], 'scheduled')
        self.assertFalse(saved['room_name'])
        self.assertIsNotNone(saved['scheduled_at'])
        self.assertTrue(response.json()['stream']['can_start'])

    @patch('live_news.views.save_live_news_poster', return_value={
        'url': 'https://res.cloudinary.com/test/live-news/poster.png',
        'public_id': 'lpu_nexus/live_news/poster',
    })
    @patch('live_news.views.live_streams')
    def test_scheduled_broadcast_shares_uploaded_poster_with_all_viewers(
        self, live_streams, save_poster
    ):
        self.login_as('staff')
        live_streams.return_value.find_one.return_value = None
        scheduled_at = timezone.localtime(
            timezone.now() + timedelta(days=1)
        ).strftime('%Y-%m-%dT%H:%M')
        poster_file = SimpleUploadedFile(
            'poster.png', b'poster-data', content_type='image/png',
        )

        response = self.client.post('/live-news/api/start/', {
            'title': 'Campus event',
            'scheduled_at': scheduled_at,
            'poster': poster_file,
        })

        self.assertEqual(response.status_code, 201)
        save_poster.assert_called_once()
        self.assertEqual(save_poster.call_args.args[0].name, 'poster.png')
        saved = live_streams.return_value.insert_one.call_args.args[0]
        self.assertEqual(
            saved['poster_url'],
            'https://res.cloudinary.com/test/live-news/poster.png',
        )
        self.assertEqual(
            response.json()['stream']['poster_url'],
            saved['poster_url'],
        )

    @patch('live_news.views.live_streams')
    def test_scheduled_broadcast_rejects_past_time(self, live_streams):
        self.login_as('staff')
        past = timezone.localtime(
            timezone.now() - timedelta(days=1)
        ).strftime('%Y-%m-%dT%H:%M')

        response = self.client.post('/live-news/api/start/', {
            'title': 'Past update',
            'scheduled_at': past,
        })

        self.assertEqual(response.status_code, 400)
        live_streams.return_value.insert_one.assert_not_called()

    @override_settings(
        LIVEKIT_URL='wss://live.example',
        LIVEKIT_API_KEY='test-key',
        LIVEKIT_API_SECRET='test-secret',
    )
    @patch('live_news.views.live_streams')
    def test_host_can_start_an_arrived_scheduled_broadcast(self, live_streams):
        self.login_as('staff')
        started = {
            **self.live_stream,
            'status': 'live',
            'room_name': 'new-live-room',
            'scheduled_at': timezone.now().replace(tzinfo=None) - timedelta(minutes=1),
        }
        live_streams.return_value.find_one_and_update.return_value = started

        response = self.client.post(f'/live-news/api/{self.stream_id}/go-live/')

        self.assertEqual(response.status_code, 200)
        query = live_streams.return_value.find_one_and_update.call_args.args[0]
        self.assertEqual(query['host_id'], 'staff-1')
        self.assertEqual(query['status'], 'scheduled')

    @patch('live_news.views.live_comments')
    @patch('live_news.views.live_participants')
    @patch('live_news.views.live_streams')
    def test_joined_student_can_post_comment_as_registration_number(
        self, live_streams, live_participants, live_comments
    ):
        self.login_as('student', 'student-1', 'Student Name')
        live_streams.return_value.find_one.return_value = {
            **self.live_stream, 'comments_enabled': True,
        }
        live_participants.return_value.find_one.return_value = {
            'display_name': '12345678',
        }
        live_comments.return_value.insert_one.return_value.inserted_id = ObjectId()

        response = self.client.post(
            f'/live-news/api/{self.stream_id}/comments/',
            {'type': 'text', 'content': 'Campus update looks good'},
        )

        self.assertEqual(response.status_code, 201)
        message = live_comments.return_value.insert_one.call_args.args[0]
        self.assertEqual(message['display_name'], '12345678')
        self.assertEqual(message['content'], 'Campus update looks good')
        self.assertEqual(response.json()['message']['type'], 'text')

    @patch('live_news.views.live_comments')
    @patch('live_news.views.live_participants')
    @patch('live_news.views.live_streams')
    def test_emoji_is_not_accepted_by_persistent_comment_endpoint(
        self, live_streams, live_participants, live_comments
    ):
        self.login_as('student', 'student-1', 'Student')
        live_streams.return_value.find_one.return_value = {
            **self.live_stream, 'comments_enabled': True,
        }
        live_participants.return_value.find_one.return_value = {
            'display_name': '12345678',
        }

        response = self.client.post(
            f'/live-news/api/{self.stream_id}/comments/',
            {'type': 'emoji', 'content': '🔥'},
        )

        self.assertEqual(response.status_code, 400)
        live_comments.return_value.insert_one.assert_not_called()

    @patch('live_news.views.live_comments')
    @patch('live_news.views.live_participants')
    @patch('live_news.views.live_streams')
    def test_joined_users_cannot_post_when_admin_disables_comments(
        self, live_streams, live_participants, live_comments
    ):
        self.login_as('student', 'student-1', 'Student')
        live_streams.return_value.find_one.return_value = {
            **self.live_stream, 'comments_enabled': False,
        }
        live_participants.return_value.find_one.return_value = {
            'display_name': '12345678',
        }

        response = self.client.post(
            f'/live-news/api/{self.stream_id}/comments/',
            {'type': 'emoji', 'content': '🔥'},
        )

        self.assertEqual(response.status_code, 403)
        live_comments.return_value.insert_one.assert_not_called()

    @patch('live_news.views.live_streams')
    def test_broadcast_host_can_toggle_live_comments(self, live_streams):
        self.login_as('staff', 'staff-1', 'Staff Member')
        live_streams.return_value.find_one.return_value = self.live_stream
        live_streams.return_value.update_one.return_value.matched_count = 1

        response = self.client.post(
            f'/live-news/api/{self.stream_id}/comments/moderate/',
            {'enabled': 'false'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['comments_enabled'])
        update = live_streams.return_value.update_one.call_args.args
        self.assertEqual(update[1]['$set']['comments_enabled'], False)

    @patch('live_news.views.live_streams')
    def test_staff_who_does_not_host_cannot_toggle_comments(self, live_streams):
        self.login_as('staff', 'staff-2', 'Other Staff')
        live_streams.return_value.find_one.return_value = self.live_stream

        response = self.client.post(
            f'/live-news/api/{self.stream_id}/comments/moderate/',
            {'enabled': 'false'},
        )

        self.assertEqual(response.status_code, 403)
        live_streams.return_value.update_one.assert_not_called()

    @override_settings(
        LIVEKIT_URL='wss://live.example',
        LIVEKIT_API_KEY='test-key',
        LIVEKIT_API_SECRET='test-secret',
    )
    @patch('live_news.views.live_participants')
    @patch('live_news.views.live_streams')
    @patch('live_news.views._remove_livekit_participant')
    def test_broadcast_host_can_remove_a_student_viewer(
        self, remove_from_livekit, live_streams, live_participants
    ):
        self.login_as('staff', 'staff-1', 'Staff Member')
        live_streams.return_value.find_one.return_value = self.live_stream
        live_participants.return_value.find_one.return_value = {
            'user_id': 'student-1',
            'identity': 'student-1-session',
            'display_name': '12345678',
            'role': 'student',
        }

        response = self.client.post(
            f'/live-news/api/{self.stream_id}/participants/student-1/remove/',
        )

        self.assertEqual(response.status_code, 200)
        remove_from_livekit.assert_called_once_with(
            'private-live-room', 'student-1-session',
        )
        self.assertEqual(
            live_streams.return_value.update_one.call_args.args[1]['$addToSet'],
            {'kicked_user_ids': 'student-1'},
        )
        live_participants.return_value.delete_one.assert_called_once()

    @override_settings(
        LIVEKIT_URL='wss://live.example',
        LIVEKIT_API_KEY='test-key',
        LIVEKIT_API_SECRET='test-secret',
    )
    @patch('live_news.views.live_participants')
    @patch('live_news.views.live_streams')
    @patch('live_news.views._remove_livekit_participant')
    def test_non_host_staff_cannot_remove_a_student_viewer(
        self, remove_from_livekit, live_streams, live_participants
    ):
        self.login_as('staff', 'staff-2', 'Other Staff')
        live_streams.return_value.find_one.return_value = self.live_stream

        response = self.client.post(
            f'/live-news/api/{self.stream_id}/participants/student-1/remove/',
        )

        self.assertEqual(response.status_code, 403)
        remove_from_livekit.assert_not_called()
        live_participants.return_value.find_one.assert_not_called()

    @patch('live_news.views.live_streams')
    def test_kicked_student_cannot_rejoin_broadcast(self, live_streams):
        self.login_as('student', 'student-1', 'Student')
        live_streams.return_value.find_one.return_value = {
            **self.live_stream,
            'kicked_user_ids': ['student-1'],
        }

        response = self.client.post(f'/live-news/api/{self.stream_id}/token/')

        self.assertEqual(response.status_code, 403)
        self.assertIn('removed you', response.json()['error'])

    @patch('live_news.views.live_comments')
    @patch('live_news.views.live_participants')
    @patch('live_news.views.live_streams')
    def test_non_joined_user_cannot_post_live_comments(
        self, live_streams, live_participants, live_comments
    ):
        self.login_as('student', 'student-1', 'Student')
        live_streams.return_value.find_one.return_value = self.live_stream
        live_participants.return_value.find_one.return_value = None

        response = self.client.post(
            f'/live-news/api/{self.stream_id}/comments/',
            {'type': 'text', 'content': 'A message'},
        )

        self.assertEqual(response.status_code, 403)
        live_comments.return_value.insert_one.assert_not_called()
