import mimetypes
import os
import posixpath
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.crypto import get_random_string
from vercel.blob import BlobClient


def _blob_token():
    token = (os.environ.get("BLOB_READ_WRITE_TOKEN") or "").strip()
    return token or None


def using_vercel_blob_storage():
    return bool(_blob_token())


def normalize_logo_url(value):
    if not value:
        return None

    raw_value = str(value).strip()
    if not raw_value:
        return None

    if raw_value.startswith(("http://", "https://", "data:")):
        return raw_value

    media_url = settings.MEDIA_URL.rstrip("/")
    if raw_value.startswith(settings.MEDIA_URL) or raw_value.startswith(f"{media_url}/"):
        return raw_value

    return f"{media_url}/{raw_value.lstrip('/')}"


def logo_filename(value):
    normalized = normalize_logo_url(value)
    if not normalized:
        return None

    parsed = urlparse(normalized)
    return posixpath.basename(parsed.path) or None


def logo_content_type(value):
    filename = logo_filename(value)
    if not filename:
        return None

    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def read_logo_bytes(value):
    normalized = normalize_logo_url(value)
    if not normalized:
        return None

    if normalized.startswith(("http://", "https://")):
        try:
            with urlopen(normalized, timeout=10) as response:
                return response.read()
        except Exception:
            return None

    storage_name = normalized
    media_url = settings.MEDIA_URL.rstrip("/")
    if storage_name.startswith(settings.MEDIA_URL):
        storage_name = storage_name[len(settings.MEDIA_URL) :].lstrip("/")
    elif storage_name.startswith(f"{media_url}/"):
        storage_name = storage_name[len(media_url) + 1 :]

    try:
        with default_storage.open(storage_name, "rb") as file_obj:
            return file_obj.read()
    except Exception:
        return None


def delete_logo_asset(value):
    normalized = normalize_logo_url(value)
    if not normalized:
        return

    if normalized.startswith(("http://", "https://")):
        token = _blob_token()
        if not token:
            return
        try:
            with BlobClient(token=token) as client:
                client.delete(normalized)
        except Exception:
            return
        return

    storage_name = normalized
    media_url = settings.MEDIA_URL.rstrip("/")
    if storage_name.startswith(settings.MEDIA_URL):
        storage_name = storage_name[len(settings.MEDIA_URL) :].lstrip("/")
    elif storage_name.startswith(f"{media_url}/"):
        storage_name = storage_name[len(media_url) + 1 :]

    try:
        default_storage.delete(storage_name)
    except Exception:
        return


def store_logo_file(file_obj, *, current_logo=None, user_id=None, experience_id=None):
    original_name = Path(getattr(file_obj, "name", "") or "logo").name or "logo"
    extension = Path(original_name).suffix.lower() or ".bin"
    basename = Path(original_name).stem or "logo"
    safe_basename = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-" for char in basename
    ).strip("-_") or "logo"
    safe_filename = f"{safe_basename}{extension}"

    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    content = file_obj.read()
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)

    content_type = (
        getattr(file_obj, "content_type", None)
        or mimetypes.guess_type(safe_filename)[0]
        or "application/octet-stream"
    )

    if using_vercel_blob_storage():
        folder = f"experience-logos/user-{user_id or 'unknown'}/experience-{experience_id or 'draft'}"
        pathname = f"{folder}/{safe_filename}"
        token = _blob_token()
        with BlobClient(token=token) as client:
            uploaded = client.put(
                pathname,
                content,
                access="public",
                content_type=content_type,
                add_random_suffix=True,
            )
        stored_value = uploaded.url
    else:
        local_folder = f"experience_logos/user_{user_id or 'unknown'}"
        random_name = f"{safe_basename}-{get_random_string(8)}{extension}"
        stored_name = default_storage.save(f"{local_folder}/{random_name}", file_obj)
        stored_value = default_storage.url(stored_name)

    if current_logo and current_logo != stored_value:
        delete_logo_asset(current_logo)

    return stored_value
