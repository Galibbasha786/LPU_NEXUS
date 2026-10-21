# core/storage.py
"""
Storage abstraction — swap between local and Cloudinary via env.
For now: local media storage with safe validation.
"""
import os
import uuid
import mimetypes
from django.conf import settings
from django.core.files.storage import default_storage


ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
ALLOWED_VIDEO_EXT = {'.mp4', '.webm', '.mov'}
MAX_IMAGE_SIZE = 8 * 1024 * 1024      # 8 MB
MAX_VIDEO_SIZE = 40 * 1024 * 1024     # 40 MB


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