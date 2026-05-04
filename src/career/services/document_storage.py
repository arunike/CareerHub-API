import mimetypes
import os
import posixpath
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from django.conf import settings
from django.core.files.storage import default_storage
from vercel.blob import BlobClient


BLOB_VALUE_PREFIX = "blob:"


def _blob_token():
    token = (os.environ.get("DOCUMENT_BLOB_READ_WRITE_TOKEN") or "").strip()
    return token or None


def using_private_document_blob_storage():
    return bool(_blob_token())


def _is_blob_value(value):
    return str(value).startswith(BLOB_VALUE_PREFIX)


def _blob_path(value):
    return str(value)[len(BLOB_VALUE_PREFIX) :].lstrip("/")


def normalize_document_url(value):
    if not value:
        return None

    raw_value = str(value).strip()
    if not raw_value:
        return None

    if _is_blob_value(raw_value):
        return raw_value

    if raw_value.startswith(("http://", "https://", "data:")):
        return raw_value

    media_url = settings.MEDIA_URL.rstrip("/")
    if raw_value.startswith(settings.MEDIA_URL) or raw_value.startswith(f"{media_url}/"):
        return raw_value

    return f"{media_url}/{raw_value.lstrip('/')}"


def document_filename(value):
    normalized = normalize_document_url(value)
    if not normalized:
        return None

    if _is_blob_value(normalized):
        return posixpath.basename(_blob_path(normalized)) or None

    parsed = urlparse(normalized)
    return posixpath.basename(parsed.path) or None


def document_content_type(value):
    filename = document_filename(value)
    if not filename:
        return None

    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def read_document_bytes(value):
    normalized = normalize_document_url(value)
    if not normalized:
        return None

    if _is_blob_value(normalized):
        token = _blob_token()
        if not token:
            return None
        try:
            with BlobClient(token=token) as client:
                blob = client.get(_blob_path(normalized), access="private", use_cache=False)
                return blob.content
        except Exception:
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


def delete_document_asset(value):
    normalized = normalize_document_url(value)
    if not normalized:
        return

    if _is_blob_value(normalized):
        token = _blob_token()
        if not token:
            return
        try:
            with BlobClient(token=token) as client:
                client.delete(_blob_path(normalized))
        except Exception:
            return
        return

    if normalized.startswith(("http://", "https://")):
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


def store_document_file(
    file_obj,
    *,
    current_file=None,
    user_id=None,
    root_document_id=None,
    document_id=None,
    version_number=None,
):
    original_name = Path(getattr(file_obj, "name", "") or "document").name or "document"
    extension = Path(original_name).suffix.lower() or ".bin"
    basename = Path(original_name).stem or "document"
    safe_basename = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-" for char in basename
    ).strip("-_") or "document"
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

    if using_private_document_blob_storage():
        root_segment = root_document_id or document_id or "draft"
        version_segment = version_number or "1"
        pathname = (
            f"documents/user-{user_id or 'unknown'}/root-{root_segment}"
            f"/v{version_segment}/{safe_filename}"
        )
        token = _blob_token()
        with BlobClient(token=token) as client:
            uploaded = client.put(
                pathname,
                content,
                access="private",
                content_type=content_type,
                add_random_suffix=False,
                overwrite=True,
            )
        stored_value = f"{BLOB_VALUE_PREFIX}{uploaded.pathname}"
    else:
        local_folder = (
            f"documents/user_{user_id or 'unknown'}/root_{root_document_id or document_id or 'draft'}"
        )
        stored_name = default_storage.save(
            f"{local_folder}/v{version_number or '1'}-{safe_filename}",
            file_obj,
        )
        stored_value = default_storage.url(stored_name)

    if current_file and current_file != stored_value:
        delete_document_asset(current_file)

    return stored_value
