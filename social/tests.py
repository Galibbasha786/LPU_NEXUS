from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from bson import ObjectId
from django.test import TestCase
from django.urls import reverse

from . import services


class SocialAccessTests(TestCase):
    @patch('social.views.get_current_user')
    def test_staff_account_cannot_open_student_social_hub(self, get_current_user):
        get_current_user.return_value = {
            'id': str(ObjectId()),
            'role': 'staff',
            'id_verification_status': 'verified',
        }
        session = self.client.session
        session['lpu_user_id'] = str(ObjectId())
        session['lpu_user_role'] = 'staff'
        session['lpu_id_verification_status'] = 'verified'
        session.save()

        response = self.client.get(reverse('social:feed'))

        self.assertRedirects(response, reverse('accounts:dashboard'), fetch_redirect_response=False)

    @patch('social.views.services.list_stories', return_value=[])
    @patch('social.views.services.list_feed', return_value=[])
    @patch('social.views.get_current_user')
    def test_verified_student_can_open_social_feed(
        self, get_current_user, _list_feed, _list_stories,
    ):
        student_id = str(ObjectId())
        get_current_user.return_value = {
            'id': student_id,
            'role': 'student',
            'active': True,
            'id_verification_status': 'verified',
            'full_name': 'LPU Student',
        }
        session = self.client.session
        session['lpu_user_id'] = student_id
        session['lpu_user_role'] = 'student'
        session['lpu_id_verification_status'] = 'verified'
        session.save()

        response = self.client.get(reverse('social:feed'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Social Hub')

    @patch('social.views.services.students_for_people', return_value=[])
    @patch('social.views.get_current_user')
    def test_student_directory_renders(
        self, get_current_user, _students_for_people,
    ):
        self._set_student_session(get_current_user)

        response = self.client.get(reverse('social:people'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Find students')

    @patch('social.views.services.students_for_people', return_value=[])
    @patch('social.views.services.list_chats', return_value=[])
    @patch('social.views.get_current_user')
    def test_chats_page_renders(
        self, get_current_user, _list_chats, _students_for_people,
    ):
        self._set_student_session(get_current_user)

        response = self.client.get(reverse('social:chats'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create a group')

    @patch('social.views.services.list_messages', return_value=[])
    @patch('social.views.services.chat_display_name', return_value='Student group')
    @patch('social.views.services.get_chat')
    @patch('social.views.get_current_user')
    def test_chat_page_renders(
        self, get_current_user, get_chat, _chat_display_name, _list_messages,
    ):
        student_id = self._set_student_session(get_current_user)
        chat_id = ObjectId()
        get_chat.return_value = {
            '_id': chat_id,
            'kind': 'group',
            'name': 'Project team',
            'owner_id': ObjectId(student_id),
        }

        response = self.client.get(
            reverse('social:chat', kwargs={'chat_id': str(chat_id)}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Project team')

    @patch('social.views.services.list_feed')
    @patch('social.views.get_current_user')
    def test_shared_post_page_renders(self, get_current_user, list_feed):
        self._set_student_session(get_current_user)
        post_id = str(ObjectId())
        list_feed.return_value = [{
            'id': post_id,
            'kind': 'post',
            'author_name': 'LPU Student',
            'author_image': '',
            'created_at': None,
            'caption': 'A student project',
            'media_url': '',
            'tagged_names': [],
            'likes_count': 0,
            'comments_count': 0,
            'liked_by_me': False,
            'comments': [],
        }]

        response = self.client.get(
            reverse('social:post', kwargs={'post_id': post_id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A student project')
        self.assertContains(response, 'data-post-share')

    @patch('social.views._broadcast_chat_event', return_value=True)
    @patch('social.views.services.share_post_in_direct_chat')
    @patch('social.views.get_current_user')
    def test_share_post_sends_to_selected_direct_chat(
        self, get_current_user, share_post, broadcast,
    ):
        student_id = self._set_student_session(get_current_user)
        peer_id, post_id, chat_id, message_id = [ObjectId() for _ in range(4)]
        share_post.return_value = (
            {'_id': chat_id},
            {
                'id': str(message_id),
                'sender_id': student_id,
                'sender_name': 'LPU Student',
                'shared_post': {'id': str(post_id), 'author_name': 'Author'},
                'created_at': datetime(2026, 11, 9, 10, 0),
            },
        )

        response = self.client.post(
            reverse('social:share_post', kwargs={'post_id': str(post_id)}),
            {'peer_id': str(peer_id)},
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['url'],
            reverse('social:chat', kwargs={'chat_id': str(chat_id)}),
        )
        share_post.assert_called_once_with(student_id, str(post_id), str(peer_id))
        broadcast.assert_called_once()

    def _set_student_session(self, get_current_user):
        student_id = str(ObjectId())
        get_current_user.return_value = {
            'id': student_id,
            'role': 'student',
            'active': True,
            'id_verification_status': 'verified',
            'full_name': 'LPU Student',
        }
        session = self.client.session
        session['lpu_user_id'] = student_id
        session['lpu_user_role'] = 'student'
        session['lpu_id_verification_status'] = 'verified'
        session.save()
        return student_id

    @patch('social.services.verified_student', return_value=None)
    def test_unverified_account_is_rejected_by_social_services(self, _verified_student):
        with self.assertRaises(services.SocialAccessError):
            services._require_student(str(ObjectId()))


class SocialServiceTests(TestCase):
    @patch('social.services.users')
    @patch('social.services.student_profiles')
    @patch('social.services.verified_student')
    def test_student_search_limits_results_to_matching_profiles_and_excludes_self(
        self, verified_student, student_profiles, users,
    ):
        current_id, matching_id, unrelated_id = [ObjectId() for _ in range(3)]
        verified_student.return_value = {'_id': current_id, 'role': 'student'}
        profile_cursor = Mock()
        profile_cursor.limit.return_value = [
            {'user_id': current_id, 'registration_number': '12300001'},
            {'user_id': matching_id, 'registration_number': '12300002'},
        ]
        student_profiles.return_value.find.return_value = profile_cursor
        users.return_value.find.return_value.sort.return_value = [{
            '_id': matching_id,
            'full_name': 'Matching student',
            'role': 'student',
        }]

        result = services.search_students_for_tag(str(current_id), '123')

        self.assertEqual([student['id'] for student in result], [str(matching_id)])
        query = users.return_value.find.call_args.args[0]
        self.assertEqual(set(query['_id']['$in']), {current_id, matching_id})
        self.assertEqual(query['_id']['$ne'], current_id)
        self.assertNotIn(unrelated_id, query['_id']['$in'])

    @patch('social.services.now')
    @patch('social.services.social_messages')
    @patch('social.services.social_chats')
    @patch('social.services.create_direct_chat')
    @patch('social.services._post_for_interaction')
    @patch('social.services._require_unblocked')
    @patch('social.services._require_student')
    def test_share_post_creates_a_direct_chat_message_with_post_preview(
        self, require_student, _require_unblocked, post_for_interaction,
        create_direct_chat, social_chats, social_messages, clock,
    ):
        sender_id, peer_id, post_id, chat_id, message_id = [ObjectId() for _ in range(5)]
        require_student.side_effect = lambda user_id: {
            '_id': ObjectId(user_id),
            'full_name': 'Sender',
        }
        post = {
            '_id': post_id,
            'author_name': 'Project author',
            'caption': 'A project idea',
            'media_url': 'https://cdn.example/project.jpg',
            'media_type': 'image',
        }
        post_for_interaction.return_value = (post, post)
        create_direct_chat.return_value = {'_id': chat_id}
        social_messages.return_value.insert_one.return_value.inserted_id = message_id
        clock.return_value = datetime(2026, 11, 9, 10, 0)

        chat, message = services.share_post_in_direct_chat(
            str(sender_id), str(post_id), str(peer_id),
        )

        self.assertEqual(chat['_id'], chat_id)
        self.assertEqual(message['sender_id'], str(sender_id))
        self.assertEqual(message['shared_post'], {
            'id': str(post_id),
            'author_name': 'Project author',
            'caption': 'A project idea',
            'media_url': 'https://cdn.example/project.jpg',
            'media_type': 'image',
        })
        create_direct_chat.assert_called_once_with(str(sender_id), str(peer_id))
        social_messages.return_value.insert_one.assert_called_once()

    @patch('social.services.social_likes')
    @patch('social.services.social_blocks')
    @patch('social.services.social_posts')
    @patch('social.services.verified_student')
    def test_blocked_student_cannot_like_a_post(
        self, verified_student, social_posts, social_blocks, social_likes,
    ):
        viewer_id, author_id, post_id = [ObjectId() for _ in range(3)]
        verified_student.side_effect = lambda user_id: {'_id': user_id, 'role': 'student'}
        post = {'_id': post_id, 'kind': 'post', 'author_id': author_id}
        social_posts.return_value.find_one.side_effect = [post, post]
        social_blocks.return_value.find_one.return_value = {'blocker_id': author_id}

        with self.assertRaises(services.SocialAccessError):
            services.toggle_like(str(viewer_id), str(post_id))

        social_likes.return_value.insert_one.assert_not_called()

    @patch('social.services.social_comments')
    @patch('social.services.social_likes')
    @patch('social.services.social_blocks')
    @patch('social.services.users')
    @patch('social.services.social_posts')
    @patch('social.services.verified_student')
    def test_feed_includes_post_and_tagged_student_name(
        self, verified_student, social_posts, users, social_blocks,
        social_likes, social_comments,
    ):
        viewer_id, author_id, tagged_id, post_id = [ObjectId() for _ in range(4)]
        verified_student.return_value = {'_id': viewer_id, 'role': 'student'}
        social_blocks.return_value.find.return_value = []
        post = {
            '_id': post_id,
            'kind': 'post',
            'author_id': author_id,
            'author_name': 'Author',
            'caption': 'A project idea',
            'tagged_user_ids': [tagged_id],
            'created_at': datetime(2026, 11, 9, 10, 0),
        }
        feed_cursor = Mock()
        feed_cursor.sort.return_value = feed_cursor
        feed_cursor.limit.return_value = [post]
        social_posts.return_value.find.side_effect = lambda query: (
            [post] if '_id' in query else feed_cursor
        )
        users.return_value.find.return_value = [
            {'_id': author_id, 'role': 'student', 'full_name': 'Author'},
            {'_id': tagged_id, 'role': 'student', 'full_name': 'Tagged student'},
        ]
        social_likes.return_value.find.return_value = []
        social_likes.return_value.aggregate.return_value = []
        social_comments.return_value.aggregate.return_value = []
        comments_cursor = Mock()
        comments_cursor.sort.return_value = comments_cursor
        comments_cursor.limit.return_value = []
        social_comments.return_value.find.return_value = comments_cursor

        result = services.list_feed(str(viewer_id))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['tagged_names'], ['Tagged student'])
        self.assertEqual(result[0]['likes_count'], 0)
        self.assertEqual(result[0]['comments_count'], 0)

    @patch('social.services.social_stories')
    @patch('social.services.verified_student')
    @patch('social.services.now')
    def test_story_expires_exactly_24_hours_after_creation(
        self, clock, verified_student, social_stories,
    ):
        student_id = ObjectId()
        created_at = datetime(2026, 11, 9, 10, 0, 0)
        clock.return_value = created_at
        verified_student.return_value = {
            '_id': student_id,
            'full_name': 'Student',
            'role': 'student',
        }
        social_stories.return_value.insert_one.return_value.inserted_id = ObjectId()

        services.create_story(
            {'id': str(student_id)},
            'Project update',
            {'url': 'https://res.cloudinary.com/demo/image/upload/test.jpg',
             'public_id': 'social/test', 'media_type': 'image'},
        )

        document = social_stories.return_value.insert_one.call_args.args[0]
        self.assertEqual(document['expires_at'], created_at + timedelta(hours=24))

    @patch('social.services.get_chat')
    @patch('social.services.verified_student')
    def test_message_rejects_non_giphy_gif_urls(self, verified_student, get_chat):
        student_id = ObjectId()
        verified_student.return_value = {'_id': student_id, 'full_name': 'Student'}
        get_chat.return_value = {
            '_id': ObjectId(),
            'kind': 'direct',
            'member_ids': [student_id, ObjectId()],
        }

        with self.assertRaisesRegex(ValueError, 'GIPHY picker'):
            services.send_message(
                str(student_id),
                str(get_chat.return_value['_id']),
                gif_url='https://example.com/image.gif',
            )

    @patch('social.services.social_chats')
    @patch('social.services.verified_student')
    def test_only_group_owner_can_delete_a_group(
        self, verified_student, social_chats,
    ):
        owner_id = ObjectId()
        chat_id = ObjectId()
        verified_student.return_value = {'_id': owner_id}
        social_chats.return_value.delete_one.return_value.deleted_count = 0

        deleted = services.delete_group(str(owner_id), str(chat_id))

        self.assertFalse(deleted)
        query = social_chats.return_value.delete_one.call_args.args[0]
        self.assertEqual(query['owner_id'], owner_id)
        self.assertEqual(query['kind'], 'group')

    @patch('social.services.requests.get')
    def test_gif_search_uses_giphy_and_returns_only_secure_giphy_urls(self, get):
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.return_value = {
            'data': [{
                'title': 'Campus idea',
                'images': {
                    'fixed_width': {'url': 'https://media1.giphy.com/media/id/giphy.gif'},
                    'fixed_width_small': {'url': 'https://media1.giphy.com/media/id/200w.gif'},
                },
            }],
        }

        results = services.search_gifs(' campus ', 'configured-key')

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Campus idea')
        self.assertEqual(
            get.call_args.kwargs['params']['q'],
            'campus',
        )
