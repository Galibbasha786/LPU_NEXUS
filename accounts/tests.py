from io import BytesIO
from unittest.mock import Mock, patch

from bson import ObjectId
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from PIL import Image
import pymupdf

from .id_card_verification import (
	MAX_OCR_IMAGE_DIMENSION,
	_prepare_image,
	_extract_image_text,
	_run_image_ocr,
	normalize_id_text,
	registration_number_matches,
	verify_student_id_card,
)
from .mongo_auth import (
	approve_student_verification,
	create_student,
	find_user_by_identifier,
	verify_recovery_answer,
)


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


class StudentAccountCreationTests(SimpleTestCase):
	@patch('accounts.mongo_auth.student_profiles')
	@patch('accounts.mongo_auth.users')
	def test_registration_profile_does_not_store_verified_id_card(
		self, users, student_profiles
	):
		users.return_value.insert_one.return_value.inserted_id = ObjectId()
		users.return_value.find_one.return_value = None
		student_profiles.return_value.find_one.return_value = None

		user, error = create_student(
			'student@lpu.in', 'pass1234', 'Student Example', '12345678',
		)

		self.assertIsNone(error)
		self.assertIsNotNone(user)
		profile = student_profiles.return_value.insert_one.call_args.args[0]
		self.assertNotIn('id_card', profile)

	@patch('accounts.mongo_auth.users')
	@patch('accounts.mongo_auth.student_profiles')
	def test_admin_can_approve_only_student_with_a_stored_id_card(
		self, student_profiles, users,
	):
		student_id = ObjectId()
		reviewer_id = ObjectId()
		student_profiles.return_value.find_one.return_value = {
			'id_card': {'public_id': 'lpu_nexus/id_cards/student'},
		}
		users.return_value.update_one.return_value.modified_count = 1

		approved = approve_student_verification(
			str(student_id), str(reviewer_id),
		)

		self.assertTrue(approved)
		query = users.return_value.update_one.call_args.args[0]
		self.assertEqual(query['id_verification_status'], 'pending')
		updates = users.return_value.update_one.call_args.args[1]['$set']
		self.assertEqual(updates['id_verification_status'], 'verified')
		self.assertEqual(updates['id_verified_by'], reviewer_id)


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
			'id_card': {
				'public_id': 'lpu_nexus/id_cards/student',
				'resource_type': 'image', 'format': 'png',
				'delivery_type': 'authenticated',
			},
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
		self.assertContains(response, '/profile/id-card/')
		self.assertContains(response, 'sidebar-profile-photo')

	@patch('accounts.views.identity_card_download_url', return_value='https://res.cloudinary.com/private-card')
	@patch('accounts.views.get_student_profile')
	def test_student_id_card_redirects_to_temporary_cloudinary_url(
		self, get_profile, cloudinary_url
	):
		get_profile.return_value = {
			'id_card': {
				'public_id': 'lpu_nexus/id_cards/student',
				'resource_type': 'image', 'format': 'png',
				'delivery_type': 'authenticated',
			},
		}
		session = self.client.session
		session['lpu_user_id'] = 'mongo-user-id'
		session['lpu_user_role'] = 'student'
		session.save()

		response = self.client.get('/profile/id-card/')

		self.assertRedirects(
			response, cloudinary_url.return_value, fetch_redirect_response=False,
		)
		cloudinary_url.assert_called_once_with(get_profile.return_value['id_card'])

	@patch('accounts.views.identity_card_download_url')
	@patch('accounts.views.get_student_profile')
	def test_student_cannot_access_another_students_id_card_route(
		self, get_profile, cloudinary_url
	):
		session = self.client.session
		session['lpu_user_id'] = 'mongo-user-id'
		session['lpu_user_role'] = 'student'
		session.save()

		response = self.client.get('/nexus-admin/students/other-user/id-card/')

		self.assertEqual(response.status_code, 403)
		get_profile.assert_not_called()
		cloudinary_url.assert_not_called()

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
	@patch('accounts.views.verify_current_password', return_value=True)
	def test_profile_deletes_account_only_after_password_and_confirmation(
		self, verify_password, get_user, delete_account
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

	@patch('accounts.views.delete_profile_image')
	@patch('accounts.views.update_profile_image', return_value=True)
	@patch('accounts.views.save_profile_image')
	@patch('accounts.views.get_user_by_id')
	def test_profile_photo_upload_stores_both_urls_and_updates_session(
		self, get_user, save_image, update_image, delete_image
	):
		get_user.return_value = {
			'_id': 'mongo-user-id',
			'role': 'student',
			'profile_image_path': 'profile_images/old.png',
			'profile_image_public_id': 'lpu_nexus/profile_images/old',
		}
		new_image = {
			'path': 'profile_images/new.png',
			'url': 'https://res.cloudinary.com/example/image/upload/new.png',
			'public_id': 'lpu_nexus/profile_images/new',
		}
		save_image.return_value = new_image
		session = self.client.session
		session['lpu_user_id'] = 'mongo-user-id'
		session['lpu_user_role'] = 'student'
		session.save()

		response = self.client.post('/profile/photo/', {
			'profile_image': SimpleUploadedFile('new.png', b'image', content_type='image/png'),
		})

		self.assertRedirects(response, '/profile/', fetch_redirect_response=False)
		update_image.assert_called_once_with('mongo-user-id', new_image)
		delete_image.assert_called_once_with({
			'profile_image_path': 'profile_images/old.png',
			'profile_image_public_id': 'lpu_nexus/profile_images/old',
		})
		self.assertEqual(self.client.session['lpu_user_image'], new_image['url'])


class RegistrationIdVerificationTests(TestCase):
	@patch('accounts.id_card_verification._extract_card_text')
	def test_card_text_must_match_name_and_uid(self, extract_text):
		extract_text.return_value = 'LOVELY PROFESSIONAL UNIVERSITY\nStudent: Asha Rao\nUID: 1234-5678'

		result = verify_student_id_card(None, 'Asha Rao', '12345678')

		self.assertTrue(result['name_matches'])
		self.assertTrue(result['registration_number_matches'])

	@patch('accounts.views.create_student')
	@patch('accounts.views.verify_student_id_card')
	@patch('accounts.views.save_identity_card')
	def test_matching_card_is_saved_and_account_is_created(
		self, save_card, verify_card, create_student
	):
		save_card.return_value = {
			'public_id': 'lpu_nexus/id_cards/student',
			'resource_type': 'image', 'format': 'png',
			'delivery_type': 'authenticated',
		}
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
		create_student.assert_called_once()
		save_card.assert_called_once()
		self.assertEqual(
			create_student.call_args.kwargs['id_card'],
			save_card.return_value,
		)
		self.assertEqual(
			create_student.call_args.kwargs['id_verification_status'],
			'verified',
		)

	@patch('accounts.views.create_student')
	@patch('accounts.views.verify_student_id_card')
	@patch('accounts.views.save_identity_card')
	def test_registration_sends_uncertain_ocr_to_private_manual_review(
		self, save_card, verify_card, create_student
	):
		save_card.return_value = {
			'public_id': 'lpu_nexus/id_cards/student',
			'resource_type': 'image', 'format': 'png',
			'delivery_type': 'authenticated',
		}
		verify_card.return_value = {
			'name_matches': False, 'registration_number_matches': True,
		}
		create_student.return_value = ({
			'_id': 'mongo-user-id', 'role': 'student',
			'full_name': 'Student Example',
			'id_verification_status': 'pending',
		}, None)
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

		self.assertRedirects(
			response, '/verification/pending/', fetch_redirect_response=False,
		)
		self.assertEqual(
			create_student.call_args.kwargs['id_verification_status'], 'pending',
		)
		self.assertEqual(
			create_student.call_args.kwargs['id_card'], save_card.return_value,
		)
		self.assertEqual(
			self.client.session['lpu_id_verification_status'], 'pending',
		)

	def test_pending_student_is_blocked_from_application_routes(self):
		session = self.client.session
		session['lpu_user_id'] = 'mongo-user-id'
		session['lpu_user_role'] = 'student'
		session['lpu_id_verification_status'] = 'pending'
		session.save()

		response = self.client.get('/profile/')

		self.assertRedirects(
			response, '/verification/pending/', fetch_redirect_response=False,
		)

	@patch('accounts.views.identity_card_download_url')
	@patch('accounts.views.get_student_profile')
	@patch('accounts.views.get_user_by_id')
	def test_staff_can_view_only_pending_student_id_cards(
		self, get_user, get_profile, download_url,
	):
		pending_user_id = str(ObjectId())
		session = self.client.session
		session['lpu_user_id'] = str(ObjectId())
		session['lpu_user_role'] = 'staff'
		session.save()
		get_user.return_value = {
			'role': 'student', 'id_verification_status': 'pending',
		}
		get_profile.return_value = {
			'id_card': {
				'public_id': 'lpu_nexus/id_cards/pending',
				'resource_type': 'image', 'format': 'png',
				'delivery_type': 'authenticated',
			},
		}
		download_url.return_value = 'https://cloudinary.example/temporary'

		response = self.client.get(
			f'/nexus-admin/students/{pending_user_id}/id-card/',
		)

		self.assertEqual(response.status_code, 302)
		self.assertEqual(response.url, download_url.return_value)

		get_user.return_value = {
			'role': 'student', 'id_verification_status': 'verified',
		}
		response = self.client.get(
			f'/nexus-admin/students/{pending_user_id}/id-card/',
		)
		self.assertEqual(response.status_code, 403)
		self.assertEqual(download_url.call_count, 1)


class IdCardDocumentReadTests(SimpleTestCase):
	def test_ocr_preparation_caps_large_images(self):
		image = Image.new('RGB', (4000, 2000), 'white')

		prepared = _prepare_image(image)

		self.assertEqual(max(prepared.size), MAX_OCR_IMAGE_DIMENSION)

	def test_ocr_retries_timed_out_images_at_a_smaller_size(self):
		image = Image.new('RGB', (1800, 900), 'white')
		pytesseract = Mock()
		pytesseract.image_to_string.side_effect = [
			RuntimeError('Tesseract process timeout'),
			'UID 12345678',
		]

		text, timed_out = _run_image_ocr(image, pytesseract, '--oem 3 --psm 6')

		self.assertEqual(text, 'UID 12345678')
		self.assertTrue(timed_out)
		self.assertEqual(pytesseract.image_to_string.call_args.args[0].size, (1200, 600))

	def test_ocr_checks_name_layout_after_first_layout_finds_uid(self):
		image = Image.new('RGB', (400, 200), 'white')
		pytesseract = Mock()
		pytesseract.image_to_string.side_effect = [
			'UID: 12345678',
			'Name: Asha Rao',
		]

		text = _extract_image_text(image, pytesseract, '12345678')

		self.assertEqual(pytesseract.image_to_string.call_count, 2)
		self.assertIn('asharao', normalize_id_text(text))
		self.assertTrue(registration_number_matches(text, '12345678'))
		pytesseract.image_to_data.assert_not_called()

	@patch('accounts.id_card_verification._extract_image_text')
	def test_pdf_ocr_scans_the_full_page_with_embedded_images(self, extract_text):
		image_data = BytesIO()
		Image.new('RGB', (16, 16), 'white').save(image_data, format='PNG')
		document = pymupdf.open()
		page = document.new_page(width=600, height=338)
		page.insert_image(
			pymupdf.Rect(10, 10, 26, 26), stream=image_data.getvalue(),
		)
		uploaded_file = SimpleUploadedFile('student-card.pdf', document.tobytes())
		document.close()
		extract_text.side_effect = lambda image, *_args: (
			'Asha Rao UID 12345678' if image.width > 100 else ''
		)

		result = verify_student_id_card(
			uploaded_file, 'Asha Rao', '12345678',
		)

		self.assertTrue(result['name_matches'])
		self.assertTrue(result['registration_number_matches'])
		self.assertGreater(extract_text.call_args.args[0].width, 100)


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
