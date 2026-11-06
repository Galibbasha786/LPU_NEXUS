# core/storage.py
"""
Storage abstraction — swap between local and Cloudinary via env.
"""
import os
import time
import uuid
import logging

import cloudinary.uploader
import cloudinary.utils
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
LIVE_NEWS_POSTER_FORMATS = {
    'JPEG': {'.jpg', '.jpeg'},
    'PNG': {'.png'},
    'WEBP': {'.webp'},
}
MAX_LIVE_NEWS_POSTER_SIZE = 8 * 1024 * 1024
MAX_PROBLEM_IMAGE_SIZE = 8 * 1024 * 1024
IDEA_VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.m4v'}
IDEA_AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.ogg', '.aac'}
PROBLEM_IMAGE_FORMATS = {
    'JPEG': {'.jpg', '.jpeg'},
    'PNG': {'.png'},
    'WEBP': {'.webp'},
}

logger = logging.getLogger(__name__)


class ProfileImageUploadError(Exception):
    """An expected validation or storage error while uploading a profile image."""


class IdentityCardStorageError(Exception):
    """An expected validation or storage error for an identity card."""


class IncidentMediaStorageError(Exception):
    """An expected storage error for emergency-report media."""


class LiveNewsPosterValidationError(Exception):
    """An expected validation error for a live-news poster."""


class LiveNewsPosterStorageError(Exception):
    """An expected remote storage error for a live-news poster."""


class ProblemImageValidationError(Exception):
    """An expected validation error for a problem-report image."""


class ProblemImageStorageError(Exception):
    """An expected remote storage error for a problem-report image."""


class IdeaMediaValidationError(Exception):
    """An expected validation error for idea audio or video."""


class IdeaMediaStorageError(Exception):
    """An expected remote storage error for idea audio or video."""


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


def save_idea_media(uploaded_file):
    if not uploaded_file:
        return None

    extension = os.path.splitext(uploaded_file.name or '')[1].lower()
    if extension not in IDEA_VIDEO_EXTENSIONS | IDEA_AUDIO_EXTENSIONS:
        raise IdeaMediaValidationError(
            'Use MP4, WEBM, MOV, M4V, MP3, WAV, M4A, OGG, or AAC media.'
        )
    if getattr(uploaded_file, 'size', 0) > MAX_VIDEO_SIZE:
        raise IdeaMediaValidationError('Audio and video files must be 40 MB or smaller.')

    try:
        credentials = _cloudinary_credentials()
    except ProfileImageUploadError as error:
        raise IdeaMediaStorageError(
            'Idea media uploads are unavailable. Contact the administrator.'
        ) from error

    public_id = uuid.uuid4().hex
    try:
        uploaded_file.seek(0)
        result = cloudinary.uploader.upload(
            uploaded_file,
            folder='lpu_nexus/idea_media',
            public_id=public_id,
            overwrite=False,
            unique_filename=False,
            resource_type='video',
            **credentials,
        )
    except Exception as error:
        logger.exception('Idea media upload to Cloudinary failed')
        raise IdeaMediaStorageError(
            'The media could not be uploaded. Please try again.'
        ) from error
    finally:
        uploaded_file.seek(0)

    media_url = result.get('secure_url')
    cloud_public_id = result.get('public_id')
    if not media_url or not cloud_public_id:
        if cloud_public_id:
            delete_idea_media({'public_id': cloud_public_id})
        raise IdeaMediaStorageError('Cloudinary did not confirm the media upload.')
    return {
        'url': media_url,
        'public_id': cloud_public_id,
        'media_type': 'audio' if extension in IDEA_AUDIO_EXTENSIONS else 'video',
    }


def delete_idea_media(media):
    if not media or not media.get('public_id'):
        return
    if not all((
        settings.CLOUDINARY_CLOUD_NAME,
        settings.CLOUDINARY_API_KEY,
        settings.CLOUDINARY_API_SECRET,
    )):
        logger.error('Cannot clean up idea media without Cloudinary credentials')
        return
    try:
        result = cloudinary.uploader.destroy(
            media['public_id'],
            resource_type='video',
            invalidate=True,
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
        )
        if result.get('result') not in {'ok', 'not found'}:
            logger.error(
                'Cloudinary did not confirm deletion of idea media %s',
                media['public_id'],
            )
    except Exception:
        logger.exception('Could not delete Cloudinary idea media %s', media['public_id'])


def save_live_news_poster(uploaded_file):
    if not uploaded_file:
        return None

    extension = os.path.splitext(uploaded_file.name or '')[1].lower()
    if extension not in {'.jpg', '.jpeg', '.png', '.webp'}:
        raise LiveNewsPosterValidationError('Use a JPG, PNG, or WEBP poster image.')
    if getattr(uploaded_file, 'size', 0) > MAX_LIVE_NEWS_POSTER_SIZE:
        raise LiveNewsPosterValidationError('Poster images must be 8 MB or smaller.')

    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise LiveNewsPosterValidationError('The selected poster is not a valid image.') from None
    finally:
        uploaded_file.seek(0)

    if extension not in LIVE_NEWS_POSTER_FORMATS.get(image_format, set()):
        raise LiveNewsPosterValidationError(
            'The poster image content does not match its file type.'
        )

    try:
        credentials = _cloudinary_credentials()
    except ProfileImageUploadError as error:
        raise LiveNewsPosterStorageError(
            'Poster uploads are unavailable. Contact the administrator.'
        ) from error

    public_id = uuid.uuid4().hex
    try:
        result = cloudinary.uploader.upload(
            uploaded_file,
            folder='lpu_nexus/live_news',
            public_id=public_id,
            overwrite=False,
            unique_filename=False,
            resource_type='image',
            type='upload',
            **credentials,
        )
    except Exception as error:
        logger.exception('Live-news poster upload to Cloudinary failed')
        raise LiveNewsPosterStorageError(
            'The poster could not be uploaded. Please try again.'
        ) from error
    finally:
        uploaded_file.seek(0)

    poster_url = result.get('secure_url')
    cloud_public_id = result.get('public_id')
    if not poster_url or not cloud_public_id:
        if cloud_public_id:
            delete_live_news_poster({'public_id': cloud_public_id})
        raise LiveNewsPosterStorageError(
            'Cloudinary did not confirm the poster upload.'
        )
    return {'url': poster_url, 'public_id': cloud_public_id}


def save_problem_image(uploaded_file):
    if not uploaded_file:
        return None

    extension = os.path.splitext(uploaded_file.name or '')[1].lower()
    if extension not in {'.jpg', '.jpeg', '.png', '.webp'}:
        raise ProblemImageValidationError('Use a JPG, PNG, or WEBP image.')
    if getattr(uploaded_file, 'size', 0) > MAX_PROBLEM_IMAGE_SIZE:
        raise ProblemImageValidationError('Images must be 8 MB or smaller.')

    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ProblemImageValidationError('The selected file is not a valid image.') from None
    finally:
        uploaded_file.seek(0)

    if extension not in PROBLEM_IMAGE_FORMATS.get(image_format, set()):
        raise ProblemImageValidationError(
            'The image content does not match its file type.'
        )

    try:
        credentials = _cloudinary_credentials()
    except ProfileImageUploadError as error:
        raise ProblemImageStorageError(
            'Problem-report image uploads are unavailable. Contact the administrator.'
        ) from error

    public_id = uuid.uuid4().hex
    try:
        result = cloudinary.uploader.upload(
            uploaded_file,
            folder='lpu_nexus/problem_reports',
            public_id=public_id,
            overwrite=False,
            unique_filename=False,
            resource_type='image',
            type='upload',
            **credentials,
        )
    except Exception as error:
        logger.exception('Problem-report image upload to Cloudinary failed')
        raise ProblemImageStorageError(
            'The image could not be uploaded. Please try again.'
        ) from error
    finally:
        uploaded_file.seek(0)

    image_url = result.get('secure_url')
    cloud_public_id = result.get('public_id')
    if not image_url or not cloud_public_id:
        if cloud_public_id:
            delete_problem_image({'public_id': cloud_public_id})
        raise ProblemImageStorageError(
            'Cloudinary did not confirm the image upload.'
        )
    return {'url': image_url, 'public_id': cloud_public_id}


def delete_problem_image(image):
    if not image or not image.get('public_id'):
        return
    if not all((
        settings.CLOUDINARY_CLOUD_NAME,
        settings.CLOUDINARY_API_KEY,
        settings.CLOUDINARY_API_SECRET,
    )):
        logger.error('Cannot clean up problem-report image without Cloudinary credentials')
        return
    try:
        result = cloudinary.uploader.destroy(
            image['public_id'],
            resource_type='image',
            invalidate=True,
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
        )
        if result.get('result') not in {'ok', 'not found'}:
            logger.error(
                'Cloudinary did not confirm deletion of problem-report image %s',
                image['public_id'],
            )
    except Exception:
        logger.exception('Could not delete problem-report image %s', image['public_id'])


def delete_live_news_poster(poster):
    if not poster or not poster.get('public_id'):
        return
    if not all((
        settings.CLOUDINARY_CLOUD_NAME,
        settings.CLOUDINARY_API_KEY,
        settings.CLOUDINARY_API_SECRET,
    )):
        logger.error('Cannot clean up live-news poster without Cloudinary credentials')
        return
    try:
        result = cloudinary.uploader.destroy(
            poster['public_id'],
            resource_type='image',
            invalidate=True,
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
        )
        if result.get('result') not in {'ok', 'not found'}:
            logger.error(
                'Cloudinary did not confirm deletion of live-news poster %s',
                poster['public_id'],
            )
    except Exception:
        logger.exception('Could not delete live-news poster %s', poster['public_id'])


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


def save_identity_card(uploaded_file, full_name, registration_number):
    extension = os.path.splitext(uploaded_file.name or '')[1].lower()
    if extension not in {'.jpg', '.jpeg', '.png', '.webp', '.pdf'}:
        raise IdentityCardStorageError('Use a JPG, PNG, WEBP, or PDF ID card.')
    if getattr(uploaded_file, 'size', 0) > 5 * 1024 * 1024:
        raise IdentityCardStorageError('ID cards must be 5 MB or smaller.')

    try:
        credentials = _cloudinary_credentials()
    except ProfileImageUploadError as error:
        raise IdentityCardStorageError(
            'Private ID-card storage is unavailable. Contact the administrator.'
        ) from error

    resource_type = 'raw' if extension == '.pdf' else 'image'
    public_id = uuid.uuid4().hex + (extension if resource_type == 'raw' else '')
    try:
        uploaded_file.seek(0)
        result = cloudinary.uploader.upload(
            uploaded_file,
            folder='lpu_nexus/id_cards',
            public_id=public_id,
            overwrite=False,
            unique_filename=False,
            resource_type=resource_type,
            type='authenticated',
            context={
                'full_name': full_name.strip(),
                'registration_number': registration_number.strip(),
            },
            **credentials,
        )
    except Exception as error:
        logger.exception('ID-card upload to Cloudinary failed')
        raise IdentityCardStorageError(
            'The ID card could not be uploaded securely. Please try again.'
        ) from error
    finally:
        uploaded_file.seek(0)

    cloud_public_id = result.get('public_id')
    if not cloud_public_id:
        raise IdentityCardStorageError('Cloudinary did not confirm the ID-card upload.')
    return {
        'public_id': cloud_public_id,
        'resource_type': result.get('resource_type', resource_type),
        'format': result.get('format', extension.lstrip('.')),
        'delivery_type': result.get('type', 'authenticated'),
    }


def identity_card_download_url(card):
    if not card or not card.get('public_id') or not card.get('format'):
        raise IdentityCardStorageError('No Cloudinary ID card is available.')
    try:
        credentials = _cloudinary_credentials()
    except ProfileImageUploadError as error:
        raise IdentityCardStorageError(
            'Private ID-card storage is unavailable. Contact the administrator.'
        ) from error
    try:
        return cloudinary.utils.private_download_url(
            card['public_id'],
            card['format'],
            resource_type=card.get('resource_type', 'image'),
            type=card.get('delivery_type', 'authenticated'),
            expires_at=int(time.time()) + 600,
            attachment=False,
            secure=True,
            **credentials,
        )
    except Exception as error:
        logger.exception('Could not generate an expiring Cloudinary ID-card URL')
        raise IdentityCardStorageError(
            'The ID card is temporarily unavailable.'
        ) from error


def incident_media_download_url(media):
    if not media or not media.get('public_id') or not media.get('format'):
        raise IncidentMediaStorageError('No emergency-report media is available.')
    try:
        credentials = _cloudinary_credentials()
    except ProfileImageUploadError as error:
        raise IncidentMediaStorageError(
            'Private emergency-media storage is unavailable.'
        ) from error
    try:
        return cloudinary.utils.private_download_url(
            media['public_id'],
            media['format'],
            resource_type=media.get('resource_type', 'image'),
            type=media.get('delivery_type', 'authenticated'),
            expires_at=int(time.time()) + 600,
            attachment=False,
            secure=True,
            **credentials,
        )
    except Exception as error:
        logger.exception('Could not generate an expiring emergency-media URL')
        raise IncidentMediaStorageError(
            'Emergency-report media is temporarily unavailable.'
        ) from error


def delete_identity_card(card):
    if not card or not card.get('public_id'):
        return
    try:
        credentials = _cloudinary_credentials()
    except ProfileImageUploadError as error:
        raise IdentityCardStorageError(
            'Private ID-card storage is unavailable. Contact the administrator.'
        ) from error
    try:
        result = cloudinary.uploader.destroy(
            card['public_id'],
            resource_type=card.get('resource_type', 'image'),
            type=card.get('delivery_type', 'authenticated'),
            invalidate=True,
            **credentials,
        )
    except Exception as error:
        logger.exception('Could not delete Cloudinary ID card %s', card['public_id'])
        raise IdentityCardStorageError(
            'The ID card could not be removed from Cloudinary.'
        ) from error
    if result.get('result') not in {'ok', 'not found'}:
        raise IdentityCardStorageError('Cloudinary did not confirm ID-card deletion.')


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
    Validate and privately store incident media in Cloudinary.
    Returns (asset metadata, error).
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

    folder = "incidents/images" if is_image else "incidents/videos"
    resource_type = 'image' if is_image else 'video'
    try:
        credentials = _cloudinary_credentials()
    except ProfileImageUploadError as error:
        return None, str(error)

    try:
        uploaded_file.seek(0)
        result = cloudinary.uploader.upload(
            uploaded_file,
            folder=f'lpu_nexus/{folder}',
            public_id=uuid.uuid4().hex,
            overwrite=False,
            unique_filename=False,
            resource_type=resource_type,
            type='authenticated',
            **credentials,
        )
    except Exception:
        logger.exception('Emergency-report media upload to Cloudinary failed')
        return None, 'The emergency media could not be uploaded. Please try again.'
    finally:
        uploaded_file.seek(0)

    public_id = result.get('public_id')
    file_format = result.get('format')
    if not public_id or not file_format:
        if public_id:
            try:
                cloudinary.uploader.destroy(
                    public_id,
                    resource_type=resource_type,
                    type='authenticated',
                    **credentials,
                )
            except Exception:
                logger.exception('Could not clean up incomplete incident media upload')
        return None, 'Cloudinary did not confirm the emergency media upload.'
    return {
        'public_id': public_id,
        'resource_type': result.get('resource_type', resource_type),
        'format': file_format,
        'delivery_type': result.get('type', 'authenticated'),
    }, None