import base64
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from config.outbound import OutboundURLError, open_outbound_url

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .ai_provider_errors import (  # noqa: F401
    AIProviderConfigurationError,
    AIProviderRequestError,
)
from .provider_secrets import (  # noqa: F401
    decrypt_ai_provider_secret,
    encrypt_ai_provider_secret,
    mask_ai_provider_secret,
    validate_ai_provider_endpoint,
)
from .json_healing import (  # noqa: F401
    heal_all_flat_arrays,
    heal_flat_array_colons,
    heal_flat_array_element,
    heal_yaml_block_scalars,
    try_heal_json,
)

AI_PROVIDER_ADAPTER_CLAUDE = "claude"
AI_PROVIDER_ADAPTER_GEMINI = "gemini"
AI_PROVIDER_ADAPTER_OPENAI = "openai"
AI_PROVIDER_ADAPTER_OPENROUTER = "openrouter"
AI_PROVIDER_ADAPTER_CUSTOM = "custom"
AI_PROVIDER_ADAPTER_CHOICES = (
    (AI_PROVIDER_ADAPTER_CLAUDE, "Claude"),
    (AI_PROVIDER_ADAPTER_GEMINI, "Gemini"),
    (AI_PROVIDER_ADAPTER_OPENAI, "OpenAI"),
    (AI_PROVIDER_ADAPTER_OPENROUTER, "OpenRouter"),
    (AI_PROVIDER_ADAPTER_CUSTOM, "Custom"),
)
DEFAULT_AI_PROVIDER_ADAPTER = AI_PROVIDER_ADAPTER_GEMINI
DEFAULT_AI_PROVIDER_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_AI_PROVIDER_MODEL = "gemini-3-flash-preview"
DEFAULT_CLAUDE_MAX_TOKENS = 4096
AI_PROVIDER_REQUEST_TIMEOUT_CEILING_SECONDS = 55


def _extract_provider_error_message(payload: object) -> str:
    preferred_keys = (
        "message",
        "detail",
        "error_description",
        "error",
        "status",
        "reason",
    )

    def collect_messages(value: object) -> list[str]:
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        if isinstance(value, list):
            messages: list[str] = []
            for item in value:
                messages.extend(collect_messages(item))
            return messages
        if isinstance(value, dict):
            messages = []
            for key in preferred_keys:
                if key in value:
                    messages.extend(collect_messages(value.get(key)))
            for nested_value in value.values():
                messages.extend(collect_messages(nested_value))
            return messages
        return []

    messages = []
    for message in collect_messages(payload):
        if message not in messages:
            messages.append(message)
    if messages:
        return " | ".join(messages[:4])

    return "The AI provider returned an unknown error."


def _request_json(*, endpoint: str, request_payload: dict, headers: dict[str, str]) -> dict:
    request_body = json.dumps(request_payload).encode("utf-8")

    try:
        configured_timeout = getattr(settings, "AI_PROVIDER_REQUEST_TIMEOUT_SECONDS", 45)
        timeout_val = min(
            max(float(configured_timeout), 1),
            AI_PROVIDER_REQUEST_TIMEOUT_CEILING_SECONDS,
        )
        with open_outbound_url(
            endpoint,
            timeout=timeout_val,
            data=request_body,
            headers=headers,
            method="POST",
        ) as response:
            raw_body = response.read().decode("utf-8")
    # Before URLError, which it subclasses.
    except OutboundURLError as exc:
        raise AIProviderConfigurationError(
            f"Provider URL is not allowed: {exc.reason}"
        ) from exc
    except HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_error = json.loads(raw_error)
        except json.JSONDecodeError:
            parsed_error = {"message": raw_error or f"Provider request failed with status {exc.code}."}
        raise AIProviderRequestError(_extract_provider_error_message(parsed_error)) from exc
    except TimeoutError as exc:
        raise AIProviderRequestError("AI provider request timed out.") from exc
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
    max_tokens: int | None = None,
    extra_headers: dict[str, str] | None = None,
):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if extra_headers:
        headers.update(extra_headers)
    request_payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        request_payload["max_tokens"] = max(1, int(max_tokens))
    return _request_json(
        endpoint=endpoint,
        request_payload=request_payload,
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


def _relay_gemini(
    *, endpoint: str, model: str, api_key: str, messages, temperature: float, max_tokens: int | None = None
):
    contents, system_parts = _messages_to_google_contents(messages)
    request_payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
        },
    }
    if max_tokens:
        request_payload["generationConfig"]["maxOutputTokens"] = max(1, int(max_tokens))
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


def _relay_claude(
    *, endpoint: str, model: str, api_key: str, messages, temperature: float, max_tokens: int | None = None
):
    claude_messages, system_prompt = _messages_to_claude(messages)
    request_payload = {
        "model": model,
        "max_tokens": max(1, int(max_tokens or DEFAULT_CLAUDE_MAX_TOKENS)),
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


def relay_ai_provider_chat_completion(*, user_settings, messages, temperature=0.2, max_tokens=None):
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
        payload = _relay_claude(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif adapter == AI_PROVIDER_ADAPTER_GEMINI:
        payload = _relay_gemini(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif adapter == AI_PROVIDER_ADAPTER_OPENAI:
        payload = _relay_chat_completions(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif adapter == AI_PROVIDER_ADAPTER_OPENROUTER:
        payload = _relay_chat_completions(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_headers={
                "HTTP-Referer": "https://careerhub.local",
                "X-OpenRouter-Title": "CareerHub",
            },
        )
    elif adapter == AI_PROVIDER_ADAPTER_CUSTOM:
        payload = _relay_chat_completions(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        raise AIProviderConfigurationError("Unsupported AI provider adapter.")

    if isinstance(payload, dict) and "choices" in payload:
        for choice in payload["choices"]:
            if isinstance(choice, dict) and "message" in choice:
                message = choice["message"]
                if isinstance(message, dict) and "content" in message:
                    content = message.get("content")
                    if isinstance(content, str):
                        message["content"] = try_heal_json(content)

    return payload


