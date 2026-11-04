from io import BytesIO
from unittest.mock import patch

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from .storage import ProfileImageUploadError, save_profile_image


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
