import builtins
from unittest.mock import patch

from bson import ObjectId
from django.test import TestCase, override_settings
import jwt


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

    def test_staff_page_renders_broadcast_controls(self):
        self.login_as('staff')

        response = self.client.get('/live-news/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Start a live broadcast')
        self.assertContains(response, 'livekit-client@2')

    @patch('live_news.views.live_streams')
    def test_student_sees_active_stream_without_room_credentials(self, live_streams):
        self.login_as('student', 'student-1', 'Student')
        collection = live_streams.return_value
        collection.find.return_value.sort.return_value.limit.return_value = [self.live_stream]

        response = self.client.get('/live-news/api/streams/')

        self.assertEqual(response.status_code, 200)
        stream = response.json()['streams'][0]
        self.assertEqual(stream['title'], 'Campus update')
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
    @patch('live_news.views.live_streams')
    def test_student_token_can_subscribe_but_cannot_publish(self, live_streams):
        self.login_as('student', 'student-1', 'Student')
        live_streams.return_value.find_one.return_value = self.live_stream

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
    @patch('live_news.views.live_streams')
    def test_only_the_stream_owner_gets_a_publishing_token(self, live_streams):
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
    @patch('live_news.views.live_streams')
    def test_missing_jwt_dependency_returns_actionable_error(self, live_streams):
        self.login_as('student', 'student-1', 'Student')
        live_streams.return_value.find_one.return_value = self.live_stream
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
