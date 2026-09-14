from pathlib import Path

from PIL import Image, UnidentifiedImageError
from django.conf import settings
from rest_framework.exceptions import ValidationError


ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}
ALLOWED_DOCUMENT_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_LOGO_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}


def _format_file_size(num_bytes):
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} bytes"


def _validate_extension(file_obj, allowed_extensions, label):
    extension = Path(getattr(file_obj, "name", "")).suffix.lower()
    if extension not in allowed_extensions:
        allowed = ", ".join(sorted(ext.lstrip(".").upper() for ext in allowed_extensions))
        raise ValidationError(f"{label} must use one of these file types: {allowed}.")


def _validate_size(file_obj, max_bytes, label):
    size = getattr(file_obj, "size", None)
    if size is None:
        return

    if size > max_bytes:
        raise ValidationError(
            f"{label} must be smaller than {_format_file_size(max_bytes)}."
        )


def _validate_content_type(file_obj, allowed_types, label):
    content_type = (getattr(file_obj, "content_type", "") or "").lower()
    if not content_type or content_type == "application/octet-stream":
        return

    if content_type not in allowed_types:
        raise ValidationError(f"{label} content type is not allowed.")


def validate_document_upload(file_obj):
    label = "Document upload"
    _validate_size(file_obj, settings.MAX_DOCUMENT_UPLOAD_BYTES, label)
    _validate_extension(file_obj, ALLOWED_DOCUMENT_EXTENSIONS, label)
    _validate_content_type(file_obj, ALLOWED_DOCUMENT_CONTENT_TYPES, label)


def validate_logo_upload(file_obj):
    label = "Logo upload"
    _validate_size(file_obj, settings.MAX_LOGO_UPLOAD_BYTES, label)
    _validate_extension(file_obj, ALLOWED_LOGO_EXTENSIONS, label)
    _validate_content_type(file_obj, ALLOWED_LOGO_CONTENT_TYPES, label)

    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        image = Image.open(file_obj)
        image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError(
            "Logo upload must be a valid PNG, JPG, GIF, or WEBP image."
        ) from exc
    finally:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)


def validate_import_upload(file_obj, allowed_extensions, label):
    _validate_size(file_obj, settings.MAX_IMPORT_FILE_BYTES, label)
    _validate_extension(file_obj, allowed_extensions, label)


def validate_import_row_count(row_count, label):
    if row_count > settings.MAX_IMPORT_ROWS:
        raise ValidationError(
            f"{label} can contain at most {settings.MAX_IMPORT_ROWS} rows."
        )
