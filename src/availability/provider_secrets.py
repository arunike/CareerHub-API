import base64
import hashlib
import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken

from .ai_provider_errors import AIProviderConfigurationError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _build_fernet_key(secret: str) -> bytes:
    raw_secret = (secret or "").strip()
    if not raw_secret:
        raise ImproperlyConfigured(
            "SECRET_KEY or AI_PROVIDER_ENCRYPTION_KEY must be set to encrypt AI provider keys."
        )

    try:
        decoded = base64.urlsafe_b64decode(raw_secret.encode("utf-8"))
        if len(decoded) == 32:
            return raw_secret.encode("utf-8")
    except Exception:
        pass

    digest = hashlib.sha256(raw_secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    encryption_secret = getattr(settings, "AI_PROVIDER_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    return Fernet(_build_fernet_key(encryption_secret))


def encrypt_ai_provider_secret(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    return _get_fernet().encrypt(normalized.encode("utf-8")).decode("utf-8")


def decrypt_ai_provider_secret(value: str) -> str:
    if not value:
        return ""
    try:
        decrypted = _get_fernet().decrypt(value.encode("utf-8"))
    except InvalidToken as exc:
        raise AIProviderConfigurationError(
            "Stored AI provider key could not be decrypted. Save a new key to continue."
        ) from exc
    return decrypted.decode("utf-8")


def mask_ai_provider_secret(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if len(normalized) <= 4:
        return "•" * len(normalized)
    return f"{'•' * 8}{normalized[-4:]}"


def validate_ai_provider_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip()
    if not normalized:
        return ""

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AIProviderConfigurationError(
            "AI provider endpoint must be a full http(s) URL."
        )

    if getattr(settings, "AI_PROVIDER_REQUIRE_HTTPS", not settings.DEBUG) and parsed.scheme != "https":
        raise AIProviderConfigurationError(
            "AI provider endpoint must use HTTPS in this environment."
        )

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise AIProviderConfigurationError("AI provider endpoint must include a hostname.")

    restrict_private_networks = getattr(
        settings, "AI_PROVIDER_RESTRICT_PRIVATE_NETWORKS", not settings.DEBUG
    )

    if restrict_private_networks and (host == "localhost" or host.endswith(".local")):
        raise AIProviderConfigurationError(
            "Local AI provider endpoints are not allowed from the backend relay."
        )

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if restrict_private_networks and ip and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    ):
        raise AIProviderConfigurationError(
            "Private-network AI provider endpoints are not allowed from the backend relay."
        )

    return normalized
