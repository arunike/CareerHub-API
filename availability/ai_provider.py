import base64
import hashlib
import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULT_AI_PROVIDER_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)
DEFAULT_AI_PROVIDER_MODEL = "gemini-2.0-flash"


class AIProviderConfigurationError(Exception):
    pass


class AIProviderRequestError(Exception):
    pass


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

    allowed_hosts = getattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", [])
    if allowed_hosts and host not in allowed_hosts:
        raise AIProviderConfigurationError(
            "AI provider host is not in the allowed host list for this deployment."
        )

    return normalized


def _extract_provider_error_message(payload: object) -> str:
    if isinstance(payload, dict):
        maybe_error = payload.get("error")
        if isinstance(maybe_error, str) and maybe_error.strip():
            return maybe_error.strip()
        if isinstance(maybe_error, dict):
            message = maybe_error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()

        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    return "The AI provider returned an unknown error."


def relay_ai_provider_chat_completion(*, user_settings, messages, temperature=0.2):
    endpoint = validate_ai_provider_endpoint(user_settings.ai_provider_endpoint or "")
    model = (user_settings.ai_provider_model or "").strip()
    api_key = user_settings.get_ai_provider_api_key()

    if not endpoint or not model or not api_key:
        raise AIProviderConfigurationError(
            "AI provider is not configured. Add your endpoint, model, and API key in Settings > AI Provider."
        )

    request_payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    request_body = json.dumps(request_payload).encode("utf-8")
    request = Request(
        endpoint,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=getattr(settings, "AI_PROVIDER_REQUEST_TIMEOUT_SECONDS", 30)) as response:
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_error = json.loads(raw_error)
        except json.JSONDecodeError:
            parsed_error = {"message": raw_error or f"Provider request failed with status {exc.code}."}
        raise AIProviderRequestError(_extract_provider_error_message(parsed_error)) from exc
    except URLError as exc:
        raise AIProviderRequestError("Failed to reach the configured AI provider.") from exc

    try:
        return json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise AIProviderRequestError("AI provider returned a non-JSON response.") from exc
