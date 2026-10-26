from unittest.mock import patch

from bson import ObjectId
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from .id_card_verification import (
	registration_number_matches,
	verify_student_id_card,
)
from .mongo_auth import find_user_by_identifier, verify_recovery_answer


class AccountRecoveryTests(SimpleTestCase):
	@patch('accounts.mongo_auth.users')
	@patch('accounts.mongo_auth.student_profiles')
	def test_uid_resolves_to_student_account(self, student_profiles, users):
		profile_collection = student_profiles.return_value
		users_collection = users.return_value
		user = {'_id': 'user-id', 'email': 'student@lpu.in'}
		profile_collection.find_one.return_value = {'user_id': 'user-id'}
		users_collection.find_one.return_value = user

		result = find_user_by_identifier('  12345678  ')

		self.assertEqual(result, user)
		profile_collection.find_one.assert_called_once_with({
			'registration_number': {'$regex': '^12345678$', '$options': 'i'}
		})
		users_collection.find_one.assert_called_once_with({'_id': 'user-id'})

	@patch('accounts.mongo_auth.users')
	@patch('accounts.mongo_auth.student_profiles')
	def test_email_prefix_resolves_to_account(self, student_profiles, users):
		student_profiles.return_value.find_one.return_value = None
		users_collection = users.return_value
		user = {'_id': 'user-id', 'email': '12345678@lpu.in'}
		users_collection.find_one.side_effect = [None, user]

		result = find_user_by_identifier('12345678')

		self.assertEqual(result, user)
		self.assertEqual(users_collection.find_one.call_count, 2)
		self.assertEqual(users_collection.find_one.call_args.args[0]['email']['$regex'], '^12345678@')

	def test_blank_recovery_answer_is_verified_as_blank(self):
		user = {'recovery_answer_hash': make_password('')}

		self.assertTrue(verify_recovery_answer(user, ''))
		self.assertFalse(verify_recovery_answer(user, 'not blank'))

	def test_uid_matching_tolerates_ocr_digit_confusions_and_separated_groups(self):
		self.assertTrue(registration_number_matches('UID: 12B4 56Z8', '12845628'))
		self.assertFalse(registration_number_matches('UID: 12345679', '12345678'))


class PasswordResetViewTests(TestCase):
	@patch('accounts.views.set_user_password')
	@patch('accounts.views.get_user_by_id')
	@patch('accounts.views.find_user_by_identifier')
	def test_blank_answer_can_complete_password_reset(self, find_user, get_user, set_password):
		user = {
			'_id': 'mongo-user-id',
			'active': True,
			'recovery_question': "What is your pet's name?",
			'recovery_answer_hash': make_password(''),
		}
		find_user.return_value = user
		get_user.return_value = user

		response = self.client.get('/')
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Lovely Professional University')
		response = self.client.get('/forgot-password/')
		self.assertEqual(response.status_code, 200)

		response = self.client.post('/forgot-password/', {
			'stage': 'identify', 'identifier': '12345678',
		})
		self.assertContains(response, "What is your pet&#x27;s name?")
		response = self.client.post('/forgot-password/', {
			'stage': 'answer', 'recovery_answer': '',
		})
		self.assertContains(response, 'New password')
		response = self.client.post('/forgot-password/', {
			'stage': 'password', 'password': 'newpass123',
			'confirm_password': 'newpass123',
		})

		self.assertRedirects(response, '/login/', fetch_redirect_response=False)
		set_password.assert_called_once_with('mongo-user-id', 'newpass123')

	@patch('accounts.views.set_user_password')
	@patch('accounts.views.get_user_by_id')
	@patch('accounts.views.find_user_by_identifier')
	def test_staff_can_reset_password_with_exact_recorded_name_and_email(
		self, find_user, get_user, set_password
	):
		staff = {
			'_id': ObjectId(),
			'role': 'staff',
			'active': True,
			'full_name': 'Staff Member',
			'email': 'staff@lpu.in',
		}
		find_user.return_value = staff
		get_user.return_value = staff

		response = self.client.post('/forgot-password/', {
			'stage': 'identify', 'identifier': 'staff@lpu.in',
		})
		self.assertContains(response, 'Full name exactly as recorded')
		response = self.client.post('/forgot-password/', {
			'stage': 'staff_verify',
			'full_name': 'Staff Member',
			'email': 'staff@lpu.in',
		})
		self.assertContains(response, 'New password')
		response = self.client.post('/forgot-password/', {
			'stage': 'password', 'password': 'newpass123',
			'confirm_password': 'newpass123',
		})

		self.assertRedirects(response, '/login/', fetch_redirect_response=False)
		set_password.assert_called_once_with(str(staff['_id']), 'newpass123')

	@patch('accounts.views.get_user_by_id')
	@patch('accounts.views.find_user_by_identifier')
	def test_staff_reset_rejects_email_with_whitespace(
		self, find_user, get_user
	):
		staff = {
			'_id': ObjectId(),
			'role': 'staff',
			'active': True,
			'full_name': 'Staff Member',
			'email': 'staff@lpu.in',
		}
		find_user.return_value = staff
		get_user.return_value = staff
		self.client.post('/forgot-password/', {
			'stage': 'identify', 'identifier': 'staff@lpu.in',
		})

		response = self.client.post('/forgot-password/', {
			'stage': 'staff_verify',
			'full_name': 'Staff Member',
			'email': 'staff @lpu.in',
		})

		self.assertContains(response, 'Full name exactly as recorded')
		self.assertNotIn('password_reset_verified', self.client.session)


class ProfileViewTests(TestCase):
	@patch('accounts.views.get_student_profile')
	@patch('accounts.views.get_user_by_id')
	def test_profile_displays_student_uid_and_editable_fields(self, get_user, get_profile):
		get_user.return_value = {
			'_id': 'mongo-user-id', 'role': 'student', 'full_name': 'Student Example',
			'email': 'student@lpu.in',
		}
		get_profile.return_value = {
			'registration_number': '12345678', 'department': 'CSE', 'year': '2',
			'id_card_path': 'id_cards/student.png',
		}
		session = self.client.session
		session['lpu_user_id'] = 'mongo-user-id'
		session['lpu_user_role'] = 'student'
		session.save()

		response = self.client.get('/profile/')

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '12345678')
		self.assertContains(response, 'Change password')
		self.assertContains(response, 'Delete account')
		self.assertContains(response, '/media/id_cards/student.png')

	@patch('accounts.views.set_user_password')
	@patch('accounts.views.verify_current_password', return_value=True)
	@patch('accounts.views.get_user_by_id')
	def test_profile_changes_password_after_current_password_verification(
		self, get_user, verify_password, set_password
	):
		get_user.return_value = {
			'_id': 'mongo-user-id', 'role': 'staff', 'full_name': 'Staff Example',
			'email': 'staff@lpu.in',
		}
		session = self.client.session
		session['lpu_user_id'] = 'mongo-user-id'
		session['lpu_user_role'] = 'staff'
		session.save()

		response = self.client.post('/profile/', {
			'action': 'change_password', 'current_password': 'oldpass',
			'new_password': 'newpass123', 'confirm_password': 'newpass123',
		})

		self.assertRedirects(response, '/profile/', fetch_redirect_response=False)
		verify_password.assert_called_once_with(get_user.return_value, 'oldpass')
		set_password.assert_called_once_with('mongo-user-id', 'newpass123')

	@patch('accounts.views.update_account_details', return_value=(True, None))
	@patch('accounts.views.get_user_by_id')
	def test_profile_updates_staff_details(self, get_user, update_details):
		get_user.return_value = {
			'_id': 'mongo-user-id', 'role': 'staff', 'full_name': 'Staff Example',
			'email': 'staff@lpu.in',
		}
		session = self.client.session
		session['lpu_user_id'] = 'mongo-user-id'
		session['lpu_user_role'] = 'staff'
		session.save()

		response = self.client.post('/profile/', {
			'action': 'update_details', 'full_name': 'Updated Staff',
			'email': 'updated@lpu.in', 'department': 'CSE',
			'designation': 'Faculty', 'phone': '1234567890',
		})

		self.assertRedirects(response, '/profile/', fetch_redirect_response=False)
		update_details.assert_called_once_with(
			'mongo-user-id', 'Updated Staff', 'updated@lpu.in', 'CSE', '',
			'Faculty', '1234567890',
		)
		self.assertEqual(self.client.session['lpu_user_name'], 'Updated Staff')

	@patch('accounts.views.delete_account')
	@patch('accounts.views.get_user_by_id')
	def test_profile_deletes_account_only_after_password_and_confirmation(
		self, get_user, delete_account
	):
		get_user.return_value = {
			'_id': 'mongo-user-id', 'role': 'staff', 'full_name': 'Staff Example',
			'email': 'staff@lpu.in',
		}
		delete_account.return_value = get_user.return_value
		session = self.client.session
		session['lpu_user_id'] = 'mongo-user-id'
		session['lpu_user_role'] = 'staff'
		session.save()

		response = self.client.post('/profile/', {
			'action': 'delete_account', 'delete_password': 'current-pass',
			'confirmation': 'DELETE',
		})

		self.assertRedirects(response, '/', fetch_redirect_response=False)
		delete_account.assert_called_once_with('mongo-user-id', 'current-pass')
		self.assertNotIn('lpu_user_id', self.client.session)


class RegistrationIdVerificationTests(TestCase):
	@patch('accounts.id_card_verification._extract_card_text')
	def test_card_text_must_match_name_and_uid(self, extract_text):
		extract_text.return_value = 'LOVELY PROFESSIONAL UNIVERSITY\nStudent: Asha Rao\nUID: 1234-5678'

		result = verify_student_id_card(None, 'Asha Rao', '12345678')

		self.assertTrue(result['name_matches'])
		self.assertTrue(result['registration_number_matches'])

	@patch('accounts.views.default_storage.save', return_value='id_cards/verified.png')
	@patch('accounts.views.create_student')
	@patch('accounts.views.verify_student_id_card')
	def test_matching_card_is_saved_and_account_is_created(
		self, verify_card, create_student, save_upload
	):
		verify_card.return_value = {
			'name_matches': True, 'registration_number_matches': True,
		}
		create_student.return_value = ({
			'_id': 'mongo-user-id', 'role': 'student', 'full_name': 'Student Example',
		}, None)
		response = self.client.post('/register/', {
			'full_name': 'Student Example',
			'registration_number': '12345678',
			'email': 'student@lpu.in',
			'department': 'CSE', 'year': '2',
			'recovery_question': 'pet', 'recovery_answer': 'Milo',
			'password': 'pass1234', 'confirm_password': 'pass1234',
			'id_card': SimpleUploadedFile('id.png', b'image', content_type='image/png'),
		})

		self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
		verify_card.assert_called_once()
		save_upload.assert_called_once()
		create_student.assert_called_once()
		self.assertEqual(
			create_student.call_args.kwargs['id_card_path'], 'id_cards/verified.png'
		)

	@patch('accounts.views.default_storage.save')
	@patch('accounts.views.create_student')
	@patch('accounts.views.verify_student_id_card')
	def test_registration_rejects_name_mismatch_before_saving_card(
		self, verify_card, create_student, save_upload
	):
		verify_card.return_value = {
			'name_matches': False, 'registration_number_matches': True,
		}
		response = self.client.post('/register/', {
			'full_name': 'Student Example',
			'registration_number': '12345678',
			'email': 'student@lpu.in',
			'department': 'CSE',
			'year': '2',
			'recovery_question': 'pet',
			'recovery_answer': 'Milo',
			'password': 'pass1234',
			'confirm_password': 'pass1234',
			'id_card': SimpleUploadedFile('id.png', b'image', content_type='image/png'),
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'name on the ID card does not match')
		create_student.assert_not_called()
		save_upload.assert_not_called()


class NotificationServiceTests(SimpleTestCase):
	@patch('accounts.notification_services.notifications')
	@patch('accounts.notification_services.users')
	def test_role_broadcast_creates_one_inbox_item_per_matching_user(
		self, users, notifications
	):
		student_id = ObjectId()
		staff_id = ObjectId()
		users.return_value.find.return_value = [
			{'_id': student_id, 'role': 'student'},
			{'_id': staff_id, 'role': 'staff'},
		]
		notifications.return_value.insert_many.return_value.inserted_ids = [
			ObjectId(), ObjectId(),
		]

		from .notification_services import notify_roles
		count = notify_roles(
			['student', 'staff'], 'Campus update', 'The library is open.',
			{'id': str(ObjectId()), 'full_name': 'Admin', 'role': 'admin'},
		)

		self.assertEqual(count, 2)
		query = users.return_value.find.call_args.args[0]
		self.assertEqual(query['role'], {'$in': ['student', 'staff']})
		documents = notifications.return_value.insert_many.call_args.args[0]
		self.assertEqual([item['user_id'] for item in documents], [student_id, staff_id])
		self.assertTrue(all(item['read'] is False for item in documents))

	@patch('accounts.notification_services.notifications')
	def test_mark_read_is_scoped_to_notification_owner(self, notifications):
		from .notification_services import mark_notification_read
		notification_id = ObjectId()
		user_id = ObjectId()
		notifications.return_value.update_one.return_value.matched_count = 1

		updated = mark_notification_read(str(notification_id), str(user_id))

		self.assertTrue(updated)
		query = notifications.return_value.update_one.call_args.args[0]
		self.assertEqual(query, {'_id': notification_id, 'user_id': user_id})
