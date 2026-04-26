import base64
import hashlib
import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

AI_PROVIDER_ADAPTER_CLAUDE = "claude"
AI_PROVIDER_ADAPTER_GEMINI = "gemini"
AI_PROVIDER_ADAPTER_OPENAI = "openai"
AI_PROVIDER_ADAPTER_OPENROUTER = "openrouter"
AI_PROVIDER_ADAPTER_CHOICES = (
    (AI_PROVIDER_ADAPTER_CLAUDE, "Claude"),
    (AI_PROVIDER_ADAPTER_GEMINI, "Gemini"),
    (AI_PROVIDER_ADAPTER_OPENAI, "OpenAI"),
    (AI_PROVIDER_ADAPTER_OPENROUTER, "OpenRouter"),
)
DEFAULT_AI_PROVIDER_ADAPTER = AI_PROVIDER_ADAPTER_GEMINI
DEFAULT_AI_PROVIDER_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_AI_PROVIDER_MODEL = "gemini-3-flash-preview"
DEFAULT_CLAUDE_MAX_TOKENS = 4096


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


def _request_json(*, endpoint: str, request_payload: dict, headers: dict[str, str]) -> dict:
    request_body = json.dumps(request_payload).encode("utf-8")
    request = Request(
        endpoint,
        data=request_body,
        headers=headers,
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


def _relay_chat_completions(
    *,
    endpoint: str,
    model: str,
    api_key: str,
    messages,
    temperature: float,
    extra_headers: dict[str, str] | None = None,
):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if extra_headers:
        headers.update(extra_headers)
    return _request_json(
        endpoint=endpoint,
        request_payload={
            "model": model,
            "messages": messages,
            "temperature": temperature,
        },
        headers=headers,
    )


def _messages_to_google_contents(messages):
    contents = []
    system_parts = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            system_parts.append({"text": content})
            continue
        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": content}],
            }
        )
    return contents, system_parts


def _extract_google_text(payload: dict) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    return "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()


def _relay_gemini(*, endpoint: str, model: str, api_key: str, messages, temperature: float):
    contents, system_parts = _messages_to_google_contents(messages)
    request_payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
        },
    }
    if system_parts:
        request_payload["system_instruction"] = {"parts": system_parts}

    normalized_endpoint = endpoint.rstrip("/")
    if normalized_endpoint.endswith(":generateContent"):
        request_endpoint = normalized_endpoint
    else:
        request_endpoint = f"{normalized_endpoint}/models/{quote(model, safe='')}:generateContent"

    payload = _request_json(
        endpoint=request_endpoint,
        request_payload=request_payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    text = _extract_google_text(payload)
    if not text:
        raise AIProviderRequestError("Google Gemini returned an empty completion.")
    return {"choices": [{"message": {"content": text}}], "provider": AI_PROVIDER_ADAPTER_GEMINI}


def _messages_to_claude(messages):
    claude_messages = []
    system_parts = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            continue
        claude_messages.append({"role": role, "content": content})
    return claude_messages, "\n\n".join(part for part in system_parts if part).strip()


def _extract_claude_text(payload: dict) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    ).strip()


def _claude_messages_endpoint(endpoint: str) -> str:
    normalized_endpoint = endpoint.rstrip("/")
    if normalized_endpoint.endswith("/v1/messages"):
        return normalized_endpoint
    if normalized_endpoint.endswith("/v1"):
        return f"{normalized_endpoint}/messages"
    return f"{normalized_endpoint}/v1/messages"


def _relay_claude(*, endpoint: str, model: str, api_key: str, messages, temperature: float):
    claude_messages, system_prompt = _messages_to_claude(messages)
    request_payload = {
        "model": model,
        "max_tokens": DEFAULT_CLAUDE_MAX_TOKENS,
        "messages": claude_messages,
        "temperature": temperature,
    }
    if system_prompt:
        request_payload["system"] = system_prompt

    payload = _request_json(
        endpoint=_claude_messages_endpoint(endpoint),
        request_payload=request_payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    text = _extract_claude_text(payload)
    if not text:
        raise AIProviderRequestError("Claude returned an empty completion.")
    return {"choices": [{"message": {"content": text}}], "provider": AI_PROVIDER_ADAPTER_CLAUDE}


def relay_ai_provider_chat_completion(*, user_settings, messages, temperature=0.2):
    endpoint = validate_ai_provider_endpoint(user_settings.ai_provider_endpoint or "")
    model = (user_settings.ai_provider_model or "").strip()
    api_key = user_settings.get_ai_provider_api_key()
    adapter = getattr(user_settings, "ai_provider_adapter", "") or AI_PROVIDER_ADAPTER_OPENAI

    if not endpoint or not model or not api_key:
        raise AIProviderConfigurationError(
            "AI provider is not configured. Add your endpoint, model, and API key in Settings > AI Provider."
        )

    if adapter == "google_gemini":
        adapter = AI_PROVIDER_ADAPTER_GEMINI
    elif adapter == "openai_compatible":
        adapter = AI_PROVIDER_ADAPTER_OPENAI

    if adapter == AI_PROVIDER_ADAPTER_CLAUDE:
        return _relay_claude(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            messages=messages,
            temperature=temperature,
        )
    if adapter == AI_PROVIDER_ADAPTER_GEMINI:
        return _relay_gemini(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            messages=messages,
            temperature=temperature,
        )
    if adapter == AI_PROVIDER_ADAPTER_OPENAI:
        return _relay_chat_completions(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            messages=messages,
            temperature=temperature,
        )
    if adapter == AI_PROVIDER_ADAPTER_OPENROUTER:
        return _relay_chat_completions(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            messages=messages,
            temperature=temperature,
            extra_headers={
                "HTTP-Referer": "https://careerhub.local",
                "X-OpenRouter-Title": "CareerHub",
            },
        )
    raise AIProviderConfigurationError("Unsupported AI provider adapter.")
