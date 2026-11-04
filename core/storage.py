# core/storage.py
"""
Storage abstraction — swap between local and Cloudinary via env.
"""
import os
import uuid
import logging

import cloudinary.uploader
from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.core.files.storage import default_storage


ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
ALLOWED_VIDEO_EXT = {'.mp4', '.webm', '.mov'}
MAX_IMAGE_SIZE = 8 * 1024 * 1024      # 8 MB
MAX_VIDEO_SIZE = 40 * 1024 * 1024     # 40 MB
MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024
PROFILE_IMAGE_FORMATS = {
    'JPEG': {'.jpg', '.jpeg'},
    'PNG': {'.png'},
    'WEBP': {'.webp'},
}

logger = logging.getLogger(__name__)


class ProfileImageUploadError(Exception):
    """An expected validation or storage error while uploading a profile image."""


def _cloudinary_credentials():
    credentials = {
        'cloud_name': settings.CLOUDINARY_CLOUD_NAME,
        'api_key': settings.CLOUDINARY_API_KEY,
        'api_secret': settings.CLOUDINARY_API_SECRET,
    }
    if not all(credentials.values()):
        raise ProfileImageUploadError(
            'Photo uploads are unavailable until Cloudinary is configured.'
        )
    return credentials


def _delete_local_profile_image(path):
    try:
        default_storage.delete(path)
    except OSError:
        logger.exception('Failed to remove local profile image %s', path)


def _validate_profile_image(uploaded_file):
    if not uploaded_file:
        raise ProfileImageUploadError('Choose an image to upload.')

    extension = os.path.splitext(uploaded_file.name or '')[1].lower()
    if extension not in {'.jpg', '.jpeg', '.png', '.webp'}:
        raise ProfileImageUploadError('Use a JPG, PNG, or WEBP image.')
    if getattr(uploaded_file, 'size', 0) > MAX_PROFILE_IMAGE_SIZE:
        raise ProfileImageUploadError('Profile photos must be 5 MB or smaller.')

    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ProfileImageUploadError('The selected file is not a valid image.') from None
    finally:
        uploaded_file.seek(0)

    if extension not in PROFILE_IMAGE_FORMATS.get(image_format, set()):
        raise ProfileImageUploadError('The image content does not match its file type.')

    return extension


def save_profile_image(uploaded_file):
    """Save a validated profile image locally and in Cloudinary."""
    extension = _validate_profile_image(uploaded_file)
    credentials = _cloudinary_credentials()
    image_id = uuid.uuid4().hex
    try:
        local_path = default_storage.save(
            f'profile_images/{image_id}{extension}',
            uploaded_file,
        )
    except OSError as error:
        logger.exception('Failed to save local profile image')
        raise ProfileImageUploadError(
            'The photo could not be saved locally. Please try again.'
        ) from error

    result = {}
    try:
        with default_storage.open(local_path, 'rb') as local_image:
            result = cloudinary.uploader.upload(
                local_image,
                folder='lpu_nexus/profile_images',
                public_id=image_id,
                overwrite=False,
                unique_filename=False,
                resource_type='image',
                **credentials,
            )
        cloud_url = result.get('secure_url')
        cloud_public_id = result.get('public_id')
        if not cloud_url or not cloud_public_id:
            raise ProfileImageUploadError('Cloudinary did not confirm the photo upload.')
    except ProfileImageUploadError:
        _delete_local_profile_image(local_path)
        if result.get('public_id'):
            delete_profile_image({'public_id': result['public_id']})
        raise
    except Exception as error:
        _delete_local_profile_image(local_path)
        logger.exception('Profile image upload to Cloudinary failed')
        raise ProfileImageUploadError(
            'The photo could not be uploaded. Please try again.'
        ) from error

    return {
        'path': local_path,
        'url': cloud_url,
        'public_id': cloud_public_id,
    }


def delete_profile_image(image):
    """Delete both stored copies of a profile image, logging cleanup failures."""
    if not image:
        return

    path = image.get('profile_image_path') or image.get('path')
    if path:
        _delete_local_profile_image(path)

    public_id = image.get('profile_image_public_id') or image.get('public_id')
    if public_id and all((
        settings.CLOUDINARY_CLOUD_NAME,
        settings.CLOUDINARY_API_KEY,
        settings.CLOUDINARY_API_SECRET,
    )):
        try:
            cloudinary.uploader.destroy(
                public_id,
                resource_type='image',
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET,
            )
        except Exception:
            logger.exception('Failed to remove Cloudinary profile image %s', public_id)


def save_incident_media(uploaded_file):
    """
    Validate + save a media file under media/incidents/<uuid>.<ext>.
    Returns (relative_path, error).
    """
    if not uploaded_file:
        return None, None

    name = uploaded_file.name or ""
    ext = os.path.splitext(name)[1].lower()

    is_image = ext in ALLOWED_IMAGE_EXT
    is_video = ext in ALLOWED_VIDEO_EXT

    if not (is_image or is_video):
        return None, "Unsupported file type. Use JPG/PNG/WEBP/GIF or MP4/WEBM/MOV."

    size = getattr(uploaded_file, 'size', 0)
    if is_image and size > MAX_IMAGE_SIZE:
        return None, "Image exceeds 8 MB."
    if is_video and size > MAX_VIDEO_SIZE:
        return None, "Video exceeds 40 MB."

    # Path
    folder = "incidents/images" if is_image else "incidents/videos"
    fname = f"{folder}/{uuid.uuid4().hex}{ext}"
    saved = default_storage.save(fname, uploaded_file)
    return saved, None