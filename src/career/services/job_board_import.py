import html
import ipaddress
import json
import logging
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError, URLError

from rest_framework.exceptions import ValidationError

from availability.ai_provider import (
    AIProviderConfigurationError,
    AIProviderRequestError,
    relay_ai_provider_chat_completion,
)


MAX_JOB_HTML_BYTES = 800_000
MAX_AI_PAGE_TEXT_CHARS = 14_000
REQUEST_TIMEOUT_SECONDS = 12

logger = logging.getLogger(__name__)


class JobPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.meta: dict[str, str] = {}
        self.ld_json: list[str] = []
        self.text_chunks: list[str] = []
        self._tag_stack: list[str] = []
        self._capture_title = False
        self._capture_ld_json = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attr_map = {name.lower(): value or '' for name, value in attrs}
        self._tag_stack.append(tag)

        if tag == 'title':
            self._capture_title = True
        elif tag == 'meta':
            key = attr_map.get('property') or attr_map.get('name')
            content = attr_map.get('content')
            if key and content:
                self.meta[key.lower()] = content.strip()
        elif tag == 'script' and attr_map.get('type', '').lower() == 'application/ld+json':
            self._capture_ld_json = True

    def handle_endtag(self, tag: str):
        if tag == 'title':
            self._capture_title = False
        elif tag == 'script':
            self._capture_ld_json = False
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str):
        value = data.strip()
        if not value:
            return
        if self._capture_title:
            self.title += f' {value}'
            return
        if self._capture_ld_json:
            self.ld_json.append(value)
            return
        if self._tag_stack and self._tag_stack[-1] in {'script', 'style', 'noscript'}:
            return
        self.text_chunks.append(value)


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = _validate_url(newurl)
        _validate_public_dns(parsed.hostname or '')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def extract_job_posting(url: str, user_settings=None) -> dict[str, str]:
    parsed = _validate_url(url)
    _validate_public_dns(parsed.hostname or '')
    html_text, final_url = _fetch_html(url)
    final_parsed = _validate_url(final_url)
    _validate_public_dns(final_parsed.hostname or '')

    parser = JobPageParser()
    parser.feed(html_text)

    structured = _extract_from_json_ld(parser.ld_json)
    title = _clean(structured.get('title') or _meta_first(parser, 'og:title', 'twitter:title') or parser.title)
    company = _clean(structured.get('company') or _meta_first(parser, 'hiringOrganization', 'company', 'og:site_name'))
    location = _clean(structured.get('location') or _meta_first(parser, 'jobLocation', 'twitter:data1'))
    description = _clean_html(structured.get('description') or _meta_first(parser, 'description', 'og:description'))
    employment_type = _normalize_employment_type(structured.get('employment_type') or '')
    salary_range = _clean(structured.get('salary_range') or '')

    title, company = _split_title_company(title, company, final_parsed.hostname or '', final_parsed.path)
    text = _visible_text(parser.text_chunks)

    if not location:
        location = _guess_location(text)
    if not description:
        description = _guess_description(text)
    if not employment_type:
        employment_type = _guess_employment_type(text)
    if not salary_range:
        salary_range = _guess_salary_range(text)

    result = {
        'source_url': final_url,
        'source_host': final_parsed.hostname or '',
        'company': company,
        'role_title': title,
        'location': location,
        'employment_type': employment_type,
        'salary_range': salary_range,
        'job_description': description,
        'extraction_method': 'rules',
        'ai_status': 'not_configured',
        'ai_message': 'AI provider is not configured. Used the built-in parser.',
    }

    if user_settings is not None:
        result = _merge_ai_extraction(
            user_settings=user_settings,
            url=final_url,
            source_host=final_parsed.hostname or '',
            page_text=text,
            baseline=result,
        )

    if not result.get('role_title') and not result.get('company'):
        raise ValidationError('Could not extract a company or role from this job page.')

    return result


def _merge_ai_extraction(
    *,
    user_settings,
    url: str,
    source_host: str,
    page_text: str,
    baseline: dict[str, str],
) -> dict[str, str]:
    if not _has_ai_provider_config(user_settings):
        return baseline

    try:
        ai_result = _extract_with_ai(
            user_settings=user_settings,
            url=url,
            source_host=source_host,
            page_text=page_text,
            baseline=baseline,
        )
    except (AIProviderConfigurationError, AIProviderRequestError, ValueError, KeyError, TypeError) as exc:
        logger.info('Job import AI extraction skipped: %s', exc)
        failed = baseline.copy()
        failed['ai_status'] = 'failed'
        failed['ai_message'] = f'AI extraction failed. Used the built-in parser. {_safe_ai_error(exc)}'
        return failed

    merged = baseline.copy()
    for key in ('company', 'role_title', 'location', 'salary_range', 'job_description'):
        value = _clean_html(ai_result.get(key, ''))
        if value:
            merged[key] = value[:5000] if key == 'job_description' else value[:255]
    employment_type = _normalize_employment_type(ai_result.get('employment_type', ''))
    if employment_type:
        merged['employment_type'] = employment_type
    merged['extraction_method'] = 'ai'
    merged['ai_status'] = 'success'
    merged['ai_message'] = 'AI extraction succeeded.'
    return merged


def _has_ai_provider_config(user_settings) -> bool:
    return bool(
        getattr(user_settings, 'ai_provider_endpoint', '')
        and getattr(user_settings, 'ai_provider_model', '')
        and user_settings.has_ai_provider_api_key()
    )


def _safe_ai_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return ''
    return message[:180]


def _extract_with_ai(
    *,
    user_settings,
    url: str,
    source_host: str,
    page_text: str,
    baseline: dict[str, str],
) -> dict[str, str]:
    messages = [
        {
            'role': 'system',
            'content': (
                'You extract job posting data from noisy career pages. '
                'Return only valid JSON with keys company, role_title, location, employment_type, salary_range, job_description. '
                'For employment_type, use one of full_time, part_time, internship, contract, freelance, or empty string. '
                'Use empty strings for unknown fields. Do not invent details. '
                'Prefer the actual job posting over navigation, marketing, or unrelated company content.'
            ),
        },
        {
            'role': 'user',
            'content': json.dumps(
                {
                    'url': url,
                    'source_host': source_host,
                    'baseline_guess': {
                        'company': baseline.get('company', ''),
                        'role_title': baseline.get('role_title', ''),
                        'location': baseline.get('location', ''),
                        'employment_type': baseline.get('employment_type', ''),
                        'salary_range': baseline.get('salary_range', ''),
                    },
                    'page_text': page_text[:MAX_AI_PAGE_TEXT_CHARS],
                },
                ensure_ascii=False,
            ),
        },
    ]
    response = relay_ai_provider_chat_completion(
        user_settings=user_settings,
        messages=messages,
        temperature=0.1,
    )
    content = response['choices'][0]['message']['content']
    return _parse_ai_json(content)


def _parse_ai_json(content: str) -> dict[str, str]:
    normalized = (content or '').strip()
    if normalized.startswith('```'):
        normalized = re.sub(r'^```(?:json)?\s*', '', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'\s*```$', '', normalized)

    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', normalized, re.DOTALL)
        if not match:
            raise ValueError('AI provider did not return JSON.')
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise ValueError('AI provider returned a non-object payload.')
    return {
        key: _as_text(parsed.get(key))
        for key in ('company', 'role_title', 'location', 'employment_type', 'salary_range', 'job_description')
    }


def _validate_url(url: str):
    try:
        parsed = urlparse((url or '').strip())
    except ValueError:
        raise ValidationError('Enter a valid job board URL.')

    if parsed.scheme != 'https':
        raise ValidationError('Job imports require an HTTPS URL.')
    if not parsed.hostname:
        raise ValidationError('Enter a valid job URL.')
    return parsed


def _validate_public_dns(hostname: str):
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValidationError('Could not resolve this job board host.')

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise ValidationError('Could not validate this job board host.')
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValidationError('This job board URL resolves to a restricted network address.')


def _fetch_html(url: str) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            'User-Agent': 'CareerHubJobImporter/1.0 (+https://careerhub.local)',
            'Accept': 'text/html,application/xhtml+xml',
        },
    )
    opener = build_opener(SafeRedirectHandler)
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type and 'application/xhtml' not in content_type:
                raise ValidationError('This URL did not return an HTML job page.')
            payload = response.read(MAX_JOB_HTML_BYTES + 1)
            if len(payload) > MAX_JOB_HTML_BYTES:
                raise ValidationError('This job page is too large to import.')
            charset = response.headers.get_content_charset() or 'utf-8'
            return payload.decode(charset, errors='replace'), response.geturl()
    except HTTPError as exc:
        raise ValidationError(f'Job board returned HTTP {exc.code}.')
    except URLError:
        raise ValidationError('Could not fetch this job board URL.')


def _extract_from_json_ld(blocks: list[str]) -> dict[str, str]:
    for block in blocks:
        for item in _json_items(block):
            job = _find_job_posting(item)
            if not job:
                continue
            company = job.get('hiringOrganization') or {}
            location = job.get('jobLocation') or {}
            if isinstance(location, list):
                location = location[0] if location else {}
            address = location.get('address') if isinstance(location, dict) else {}
            return {
                'title': _as_text(job.get('title')),
                'company': _as_text(company.get('name') if isinstance(company, dict) else company),
                'location': _format_address(address if isinstance(address, dict) else location),
                'employment_type': _as_text(job.get('employmentType')),
                'salary_range': _format_salary(job.get('baseSalary')),
                'description': _as_text(job.get('description')),
            }
    return {}


def _json_items(block: str) -> list[Any]:
    try:
        parsed = json.loads(block)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else [parsed]


def _find_job_posting(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    item_type = item.get('@type')
    if item_type == 'JobPosting' or (isinstance(item_type, list) and 'JobPosting' in item_type):
        return item
    graph = item.get('@graph')
    if isinstance(graph, list):
        for child in graph:
            found = _find_job_posting(child)
            if found:
                return found
    return None


def _meta_first(parser: JobPageParser, *keys: str) -> str:
    for key in keys:
        value = parser.meta.get(key.lower())
        if value:
            return value
    return ''


def _split_title_company(title: str, company: str, host: str, path: str) -> tuple[str, str]:
    cleaned_title = re.sub(r'\s+', ' ', title).strip(' |–-')
    cleaned_company = company.strip()

    patterns = [
        r'^Job Application for (?P<title>.+?) at (?P<company>.+)$',
        r'^(?P<title>.+?) at (?P<company>.+?) \| LinkedIn$',
        r'^(?P<title>.+?) - (?P<company>.+?) - LinkedIn$',
        r'^(?P<company>.+?) is hiring a (?P<title>.+?)$',
        r'^(?P<title>.+?) \| Careers at (?P<company>.+)$',
        r'^(?P<title>.+?) - (?P<company>.+?) Careers$',
        r'^(?P<company>.+?) Careers - (?P<title>.+)$',
    ]
    for pattern in patterns:
        match = re.match(pattern, cleaned_title, re.IGNORECASE)
        if match:
            cleaned_title = match.group('title').strip()
            cleaned_company = cleaned_company or match.group('company').strip()
            break

    if not cleaned_company:
        cleaned_company = _company_from_host_path(host, path)

    return cleaned_title[:255], cleaned_company[:255]


def _company_from_host_path(host: str, path: str) -> str:
    host = host.lower()
    path_parts = [part for part in path.split('/') if part]

    if host.endswith('lever.co') and path_parts:
        return _humanize_slug(path_parts[0])
    if 'greenhouse.io' in host and path_parts:
        return _humanize_slug(path_parts[0])
    if 'myworkdayjobs.com' in host:
        first_label = host.split('.')[0]
        if first_label not in {'www', 'wd1', 'wd2', 'wd3', 'wd5'}:
            return _humanize_slug(first_label)

    labels = host.split('.')
    if labels and labels[0] not in {'www', 'jobs', 'careers', 'boards', 'apply'}:
        return _humanize_slug(labels[0])
    return ''


def _humanize_slug(value: str) -> str:
    return re.sub(r'[-_]+', ' ', value).strip().title()


def _format_address(value: Any) -> str:
    if not isinstance(value, dict):
        return _as_text(value)
    parts = [
        value.get('addressLocality'),
        value.get('addressRegion'),
        value.get('addressCountry'),
    ]
    return ', '.join(_as_text(part) for part in parts if _as_text(part))


def _format_salary(value: Any) -> str:
    if not value:
        return ''
    if isinstance(value, list):
        return _format_salary(value[0]) if value else ''
    if not isinstance(value, dict):
        return _as_text(value)

    currency = _as_text(value.get('currency') or value.get('salaryCurrency') or '')
    amount = value.get('value') if 'value' in value else value
    if isinstance(amount, list):
        amount = amount[0] if amount else {}
    if isinstance(amount, dict):
        min_value = amount.get('minValue')
        max_value = amount.get('maxValue')
        direct_value = amount.get('value')
        unit = _as_text(amount.get('unitText') or value.get('unitText') or '')
    else:
        min_value = None
        max_value = None
        direct_value = amount
        unit = _as_text(value.get('unitText') or '')

    prefix = '$' if currency.upper() in {'USD', 'US DOLLAR', 'US DOLLARS'} else (f'{currency} ' if currency else '')
    suffix = f' {unit.lower()}' if unit else ''
    if min_value and max_value:
        return f'{prefix}{_format_salary_number(min_value)} - {prefix}{_format_salary_number(max_value)}{suffix}'.strip()
    if direct_value:
        return f'{prefix}{_format_salary_number(direct_value)}{suffix}'.strip()
    return ''


def _format_salary_number(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _as_text(value)
    if numeric >= 1000 and numeric % 1000 == 0:
        return f'{int(numeric / 1000)}k'
    return f'{numeric:g}'


def _as_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, dict):
        return _format_address(value)
    if isinstance(value, list):
        return ', '.join(_as_text(item) for item in value if _as_text(item))
    return str(value).strip()


def _visible_text(chunks: list[str]) -> str:
    return _clean(' '.join(chunks))


def _guess_location(text: str) -> str:
    match = re.search(r'\b(Location|Office|Workplace)\s*:?\s+([A-Z][A-Za-z .,-]{2,80})', text)
    return match.group(2).strip(' .,-') if match else ''


def _guess_description(text: str) -> str:
    if not text:
        return ''
    markers = ['About the role', 'About this job', 'Job Description', 'Responsibilities', 'What you will do']
    start = 0
    for marker in markers:
        idx = text.lower().find(marker.lower())
        if idx >= 0:
            start = idx
            break
    return text[start:start + 5000].strip()


def _normalize_employment_type(value: str) -> str:
    normalized = _clean(str(value or '')).lower().replace('-', ' ').replace('_', ' ')
    if not normalized:
        return ''
    if any(token in normalized for token in ['internship', 'intern ', 'intern']):
        return 'internship'
    if any(token in normalized for token in ['part time', 'parttime']):
        return 'part_time'
    if any(token in normalized for token in ['contract', 'contractor', 'temporary']):
        return 'contract'
    if any(token in normalized for token in ['freelance', 'consultant']):
        return 'freelance'
    if any(token in normalized for token in ['full time', 'fulltime', 'regular', 'permanent']):
        return 'full_time'
    return ''


def _guess_employment_type(text: str) -> str:
    return _normalize_employment_type(text[:5000])


def _guess_salary_range(text: str) -> str:
    salary_patterns = [
        r'(?i)(?:salary|compensation|pay range|base pay|annual pay)[^$]{0,80}(\$[\d,.]+k?\s*(?:-|–|to)\s*\$?[\d,.]+k?(?:\s*(?:per year|yearly|annually|/year))?)',
        r'(\$[\d,.]+k?\s*(?:-|–|to)\s*\$?[\d,.]+k?(?:\s*(?:per year|yearly|annually|/year))?)',
    ]
    for pattern in salary_patterns:
        match = re.search(pattern, text)
        if match:
            return _clean(match.group(1))[:100]
    return ''


def _clean(value: str) -> str:
    return html.unescape(re.sub(r'\s+', ' ', value or '')).strip()


def _clean_html(value: str) -> str:
    return _clean(re.sub(r'<[^>]+>', ' ', value or ''))
