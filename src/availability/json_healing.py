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
