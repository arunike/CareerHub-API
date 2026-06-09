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

    return normalized


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
    request = Request(
        endpoint,
        data=request_body,
        headers=headers,
        method="POST",
    )

    try:
        configured_timeout = getattr(settings, "AI_PROVIDER_REQUEST_TIMEOUT_SECONDS", 45)
        timeout_val = min(
            max(float(configured_timeout), 1),
            AI_PROVIDER_REQUEST_TIMEOUT_CEILING_SECONDS,
        )
        with urlopen(request, timeout=timeout_val) as response:
            raw_body = response.read().decode("utf-8")
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


def heal_yaml_block_scalars(text: str) -> str:
    import re
    lines = text.splitlines()
    result_lines = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        match = re.match(r'^(.*?)("[^"]+"\s*:\s*)(>\s*|>\-\s*|\|\s*)$', line)
        if match:
            leading = match.group(1)
            prefix = match.group(2)
            block_lines = []
            i += 1
            while i < n:
                next_line = lines[i]
                if re.match(r'^\s*"[^"]+"\s*:', next_line) or re.match(r'^\s*[\}\]]\s*,?\s*$', next_line):
                    break
                block_lines.append(next_line)
                i += 1
            
            # Find common minimum indentation among non-empty lines
            min_indent = None
            for bline in block_lines:
                stripped_bline = bline.lstrip()
                if stripped_bline:
                    indent_len = len(bline) - len(stripped_bline)
                    if min_indent is None or indent_len < min_indent:
                        min_indent = indent_len
            
            if min_indent is not None and min_indent > 0:
                cleaned_block_lines = []
                for bline in block_lines:
                    if len(bline) >= min_indent:
                        cleaned_block_lines.append(bline[min_indent:])
                    else:
                        cleaned_block_lines.append(bline.lstrip())
                block_lines = cleaned_block_lines

            combined = "\n".join(block_lines).strip()
            if combined.startswith('"') and combined.endswith('"'):
                combined = combined[1:-1]
            elif combined.startswith('**"') and combined.endswith('"'):
                combined = combined.replace('**"', '**')
                if combined.endswith('"'):
                    combined = combined[:-1]
            
            escaped = combined.replace('\\', '\\\\').replace('"', '\\"')
            escaped = escaped.replace('\n', '\\n')
            result_lines.append(f'{leading}{prefix}"{escaped}"')
        else:
            result_lines.append(line)
            i += 1
            
    return "\n".join(result_lines)


def heal_flat_array_element(line: str) -> str:
    import re
    normalized = line.replace('“', '"').replace('”', '"')
    stripped = normalized.strip()
    has_comma = stripped.endswith(',')
    if has_comma:
        stripped = stripped[:-1].strip()
        
    if not stripped:
        return line
        
    if stripped.startswith('"') and stripped.endswith('"'):
        indent = line[:len(line) - len(line.lstrip())]
        return indent + stripped + (',' if has_comma else '')
        
    cleaned = re.sub(r'^\*\*+\s*[“"”]', '**', stripped)
    cleaned = re.sub(r'[“"”]\s*\*\*+$', '**', cleaned)
    cleaned = cleaned.replace('**"', '**').replace('"**', '**')
    
    if cleaned.startswith('"'):
        cleaned = cleaned[1:]
    if cleaned.endswith('"'):
        cleaned = cleaned[:-1]
        
    escaped = cleaned.replace('\\', '\\\\').replace('"', '\\"')
    healed = f'"{escaped}"'
    if has_comma:
        healed += ','
        
    indent = line[:len(line) - len(line.lstrip())]
    return indent + healed


def try_heal_json(text: str) -> str:
    # 0. Heal YAML-like block scalars (e.g. key: >)
    healed_yaml = heal_yaml_block_scalars(text)

    # 1. Extract potential JSON block (handles markdown fences, surrounding text, etc.)
    extracted = extract_json_block(healed_yaml)
    
    # 2. Heal misplaced markdown bold quotes
    import re
    # Heal leading bold quotes (e.g., **" or **“ -> "**)
    healed_bold = re.sub(r'(^|[,\[\{\s])(\*\*+)\s*[“"”]', r'\1"\2', extracted)
    # Heal trailing bold quotes (e.g., "** at the end of a string -> **")
    healed_bold = re.sub(r'[“"”]\s*(\*\*+)(?=\s*[,\]\}]|$)', r'\1"', healed_bold)
    
    # 3. Heal unescaped newlines in strings
    healed = fix_unescaped_json_newlines(healed_bold)
    
    # 4. Verify if it is valid JSON
    try:
        import json
        json.loads(healed)
        return healed # Valid JSON! Return the clean healed JSON string
    except Exception:
        pass

    # 5. Try healing flat array colons first, then apply newline healing
    try:
        healed_arrays = heal_all_flat_arrays(healed_bold)
        healed_both = fix_unescaped_json_newlines(healed_arrays)
        import json
        json.loads(healed_both)
        return healed_both
    except Exception:
        pass
        
    # 6. Try removing unmatched brackets/braces, then heal flat arrays and newlines
    try:
        cleaned_brackets = remove_unmatched_brackets_braces(healed_bold)
        healed_arrays = heal_all_flat_arrays(cleaned_brackets)
        healed_both = fix_unescaped_json_newlines(healed_arrays)
        import json
        json.loads(healed_both)
        return healed_both
    except Exception:
        pass
        
    # 7. Global smart quote replacement fallback
    try:
        healed_quotes = healed_bold.replace('“', '"').replace('”', '"')
        healed_quotes_newlines = fix_unescaped_json_newlines(healed_quotes)
        import json
        json.loads(healed_quotes_newlines)
        return healed_quotes_newlines
    except Exception:
        pass
        
    # Not valid JSON. Return original text untouched.
    return text


def heal_flat_array_colons(array_content: str) -> str:
    import re
    # Handle case 1: "key": "value" (both quoted)
    pattern1 = r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"'
    # Handle case 2: "key": value" (missing opening quote for value)
    pattern2 = r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*:\s*([^"\s][^"\n\r]*)"'
    
    def replacer(match):
        g1 = match.group(1)
        g2 = match.group(2)
        return f'"{g1}: {g2}"'
        
    healed = re.sub(pattern1, replacer, array_content)
    healed = re.sub(pattern2, replacer, healed)
    return healed


def heal_all_flat_arrays(text: str) -> str:
    result = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == '[':
            # Check if this [ is a valid JSON array start
            # (i.e. preceded by :, [, ,, or { or start of text)
            p = i - 1
            while p >= 0 and text[p].isspace():
                p -= 1
            is_valid_start = (p < 0 or text[p] == ':')
            
            if is_valid_start:
                depth = 1
                j = i + 1
                while j < n and depth > 0:
                    if text[j] == '[':
                        depth += 1
                    elif text[j] == ']':
                        depth -= 1
                    j += 1
                
                if depth == 0:
                    array_block = text[i:j]
                    inner_content = text[i+1:j-1]
                    if '{' not in inner_content and '}' not in inner_content:
                        # Heal array elements line by line
                        lines = inner_content.splitlines()
                        healed_lines = [heal_flat_array_element(line) for line in lines]
                        healed_inner = "\n".join(healed_lines)
                        healed_inner = heal_flat_array_colons(healed_inner)
                        result.append('[' + healed_inner + ']')
                    else:
                        result.append(array_block)
                    i = j
                else:
                    result.append(text[i])
                    i += 1
            else:
                result.append(text[i])
                i += 1
        else:
            result.append(text[i])
            i += 1
            
    return "".join(result)


def remove_unmatched_brackets_braces(text: str) -> str:
    n = len(text)
    stack = []  # stores (char, index)
    to_remove = set()
    
    in_string = False
    escaped = False
    
    i = 0
    while i < n:
        char = text[i]
        if char == '"' and not escaped:
            in_string = not in_string
            
        if not in_string:
            if char in {'{', '['}:
                stack.append((char, i))
            elif char == '}':
                if stack and stack[-1][0] == '{':
                    stack.pop()
                else:
                    to_remove.add(i)
            elif char == ']':
                if stack and stack[-1][0] == '[':
                    stack.pop()
                else:
                    to_remove.add(i)
                    
        if char == '\\' and not escaped:
            escaped = True
        else:
            escaped = False
        i += 1
        
    if not to_remove:
        return text
    
    return "".join(text[idx] for idx in range(n) if idx not in to_remove)



def extract_json_block(text: str) -> str:
    cleaned = text.strip()
    first_brace = cleaned.find("{")
    first_bracket = cleaned.find("[")
    
    start_idx = -1
    end_char = ""
    
    if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        start_idx = first_brace
        end_char = "}"
    elif first_bracket != -1:
        start_idx = first_bracket
        end_char = "]"
        
    if start_idx == -1:
        return text
        
    end_idx = cleaned.rfind(end_char)
    if end_idx == -1 or end_idx < start_idx:
        return text
        
    return cleaned[start_idx:end_idx + 1]


def fix_unescaped_json_newlines(json_str: str) -> str:
    in_string = False
    escaped = False
    result = []
    for char in json_str:
        if char == '"' and not escaped:
            in_string = not in_string
        
        if in_string:
            if char == '\n':
                result.append('\\n')
            elif char == '\r':
                result.append('\\r')
            else:
                result.append(char)
        else:
            result.append(char)
            
        if char == '\\' and not escaped:
            escaped = True
        else:
            escaped = False
            
    return "".join(result)
