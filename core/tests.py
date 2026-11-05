from io import BytesIO
from unittest.mock import patch

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from .storage import (
    IdentityCardStorageError,
    LiveNewsPosterStorageError,
    LiveNewsPosterValidationError,
    ProfileImageUploadError,
    delete_identity_card,
    identity_card_download_url,
    save_live_news_poster,
    save_identity_card,
    save_profile_image,
)


class ProfileImageStorageTests(SimpleTestCase):
    def setUp(self):
        image_buffer = BytesIO()
        Image.new('RGB', (2, 2), color='maroon').save(image_buffer, format='PNG')
        self.image_bytes = image_buffer.getvalue()

    @override_settings(
        CLOUDINARY_CLOUD_NAME='test-cloud',
        CLOUDINARY_API_KEY='test-key',
        CLOUDINARY_API_SECRET='test-secret',
    )
    @patch('core.storage.cloudinary.uploader.upload')
    @patch('core.storage.default_storage.open')
    @patch('core.storage.default_storage.save', return_value='profile_images/photo.png')
    def test_profile_image_is_saved_locally_and_uploaded_to_cloudinary(
        self, save_local, open_local, upload_cloud
    ):
        open_local.return_value.__enter__.return_value = BytesIO(self.image_bytes)
        upload_cloud.return_value = {
            'secure_url': 'https://res.cloudinary.com/test/photo.png',
            'public_id': 'lpu_nexus/profile_images/photo',
        }
        uploaded_file = SimpleUploadedFile(
            'photo.png', self.image_bytes, content_type='image/png',
        )

        result = save_profile_image(uploaded_file)

        self.assertEqual(result['path'], 'profile_images/photo.png')
        self.assertEqual(result['url'], upload_cloud.return_value['secure_url'])
        self.assertEqual(result['public_id'], upload_cloud.return_value['public_id'])
        save_local.assert_called_once()
        upload_cloud.assert_called_once()

    @override_settings(
        CLOUDINARY_CLOUD_NAME='',
        CLOUDINARY_API_KEY='',
        CLOUDINARY_API_SECRET='',
    )
    @patch('core.storage.default_storage.save')
    def test_cloudinary_configuration_is_required_before_local_save(self, save_local):
        uploaded_file = SimpleUploadedFile(
            'photo.png', self.image_bytes, content_type='image/png',
        )

        with self.assertRaisesMessage(
            ProfileImageUploadError, 'Cloudinary is configured'
        ):
            save_profile_image(uploaded_file)

        save_local.assert_not_called()

    def test_profile_image_rejects_mismatched_content(self):
        uploaded_file = SimpleUploadedFile(
            'photo.jpg', self.image_bytes, content_type='image/jpeg',
        )

        with self.assertRaisesMessage(
            ProfileImageUploadError, 'does not match its file type'
        ):
            save_profile_image(uploaded_file)


class IdentityCardStorageTests(SimpleTestCase):
    @override_settings(
        CLOUDINARY_CLOUD_NAME='test-cloud',
        CLOUDINARY_API_KEY='test-key',
        CLOUDINARY_API_SECRET='test-secret',
    )
    @patch('core.storage.cloudinary.uploader.upload')
    def test_identity_card_is_uploaded_as_authenticated_cloudinary_asset(self, upload):
        upload.return_value = {
            'public_id': 'lpu_nexus/id_cards/card-id',
            'resource_type': 'image',
            'format': 'png',
            'type': 'authenticated',
        }
        uploaded_file = SimpleUploadedFile('card.png', b'image-data')

        result = save_identity_card(uploaded_file, 'Student Example', '12345678')

        self.assertEqual(result['public_id'], upload.return_value['public_id'])
        self.assertEqual(result['delivery_type'], 'authenticated')
        self.assertEqual(upload.call_args.kwargs['type'], 'authenticated')
        self.assertEqual(upload.call_args.kwargs['context'], {
            'full_name': 'Student Example',
            'registration_number': '12345678',
        })

    @override_settings(
        CLOUDINARY_CLOUD_NAME='test-cloud',
        CLOUDINARY_API_KEY='test-key',
        CLOUDINARY_API_SECRET='test-secret',
    )
    @patch('core.storage.cloudinary.utils.private_download_url')
    def test_identity_card_download_url_is_short_lived_and_cloudinary_signed(self, download):
        card = {
            'public_id': 'lpu_nexus/id_cards/card-id',
            'resource_type': 'raw',
            'format': 'pdf',
            'delivery_type': 'authenticated',
        }
        download.return_value = 'https://res.cloudinary.com/private-card'

        result = identity_card_download_url(card)

        self.assertEqual(result, download.return_value)
        self.assertEqual(download.call_args.kwargs['type'], 'authenticated')
        self.assertEqual(download.call_args.kwargs['resource_type'], 'raw')
        self.assertGreater(download.call_args.kwargs['expires_at'], 0)

    @override_settings(
        CLOUDINARY_CLOUD_NAME='test-cloud',
        CLOUDINARY_API_KEY='test-key',
        CLOUDINARY_API_SECRET='test-secret',
    )
    @patch('core.storage.cloudinary.uploader.destroy')
    def test_identity_card_deletes_authenticated_cloudinary_asset(self, destroy):
        destroy.return_value = {'result': 'ok'}

        delete_identity_card({
            'public_id': 'lpu_nexus/id_cards/card-id',
            'resource_type': 'raw',
            'delivery_type': 'authenticated',
        })

        self.assertEqual(destroy.call_args.args[0], 'lpu_nexus/id_cards/card-id')
        self.assertEqual(destroy.call_args.kwargs['type'], 'authenticated')
        self.assertEqual(destroy.call_args.kwargs['resource_type'], 'raw')

    @override_settings(
        CLOUDINARY_CLOUD_NAME='',
        CLOUDINARY_API_KEY='',
        CLOUDINARY_API_SECRET='',
    )
    def test_identity_card_upload_fails_if_private_cloudinary_storage_is_not_configured(self):
        with self.assertRaises(IdentityCardStorageError):
            save_identity_card(SimpleUploadedFile('card.png', b'image-data'), 'Name', '123')


class LiveNewsPosterStorageTests(SimpleTestCase):
    def setUp(self):
        image_buffer = BytesIO()
        Image.new('RGB', (2, 2), color='maroon').save(image_buffer, format='PNG')
        self.image_bytes = image_buffer.getvalue()

    @override_settings(
        CLOUDINARY_CLOUD_NAME='test-cloud',
        CLOUDINARY_API_KEY='test-key',
        CLOUDINARY_API_SECRET='test-secret',
    )
    @patch('core.storage.cloudinary.uploader.upload')
    def test_poster_is_uploaded_to_public_cloudinary_storage(self, upload):
        upload.return_value = {
            'secure_url': 'https://res.cloudinary.com/test/live-news/poster.png',
            'public_id': 'lpu_nexus/live_news/poster',
        }
        uploaded_file = SimpleUploadedFile(
            'poster.png', self.image_bytes, content_type='image/png',
        )

        result = save_live_news_poster(uploaded_file)

        self.assertEqual(result['url'], upload.return_value['secure_url'])
        self.assertEqual(result['public_id'], upload.return_value['public_id'])
        self.assertEqual(upload.call_args.kwargs['folder'], 'lpu_nexus/live_news')
        self.assertEqual(upload.call_args.kwargs['resource_type'], 'image')

    @patch('core.storage.cloudinary.uploader.upload')
    def test_poster_rejects_file_content_that_does_not_match_extension(self, upload):
        uploaded_file = SimpleUploadedFile(
            'poster.jpg', self.image_bytes, content_type='image/jpeg',
        )

        with self.assertRaisesMessage(
            LiveNewsPosterValidationError, 'does not match its file type'
        ):
            save_live_news_poster(uploaded_file)

        upload.assert_not_called()

    @override_settings(
        CLOUDINARY_CLOUD_NAME='',
        CLOUDINARY_API_KEY='',
        CLOUDINARY_API_SECRET='',
    )
    def test_poster_requires_cloudinary_configuration(self):
        uploaded_file = SimpleUploadedFile(
            'poster.png', self.image_bytes, content_type='image/png',
        )

        with self.assertRaises(LiveNewsPosterStorageError):
            save_live_news_poster(uploaded_file)
