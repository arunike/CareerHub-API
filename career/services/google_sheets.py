import base64
import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime
from datetime import timedelta
from datetime import time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from availability.models import Event, EventCategory, UserSettings
from career.models import Application, Company, GoogleSheetSyncConfig, GoogleSheetSyncRow


APPLICATION_DEFAULT_MAPPING = {
    'external_id': 'External ID',
    'company_name': 'Company',
    'role_title': 'Role',
    'status': 'Status',
    'job_link': 'Job Link',
    'salary_range': 'Salary',
    'location': 'Location',
    'office_location': 'Office Location',
    'date_applied': 'Date Applied',
    'notes': 'Notes',
}

EVENT_DEFAULT_MAPPING = {
    'external_id': 'External ID',
    'name': 'Name',
    'date': 'Date',
    'start_time': 'Start Time',
    'end_time': 'End Time',
    'timezone': 'Timezone',
    'location_type': 'Location Type',
    'location': 'Location',
    'meeting_link': 'Meeting Link',
    'category': 'Category',
    'notes': 'Notes',
}

DEFAULT_APPLICATION_STAGES = [
    {'key': 'APPLIED', 'label': 'Applied', 'shortLabel': 'Apply', 'tone': 'bg-blue-500'},
    {'key': 'OA', 'label': 'Online Assessment', 'shortLabel': 'OA', 'tone': 'bg-violet-500'},
    {'key': 'SCREEN', 'label': 'Phone Screen', 'shortLabel': 'Phone', 'tone': 'bg-sky-500'},
    {'key': 'ROUND_1', 'label': '1st Round', 'shortLabel': 'R1', 'tone': 'bg-amber-400'},
    {'key': 'ROUND_2', 'label': '2nd Round', 'shortLabel': 'R2', 'tone': 'bg-amber-500'},
    {'key': 'ROUND_3', 'label': '3rd Round', 'shortLabel': 'R3', 'tone': 'bg-orange-500'},
    {'key': 'ROUND_4', 'label': '4th Round', 'shortLabel': 'R4', 'tone': 'bg-orange-600'},
    {'key': 'ONSITE', 'label': 'Onsite Interview', 'shortLabel': 'Onsite', 'tone': 'bg-red-500'},
    {'key': 'OFFER', 'label': 'Offer', 'shortLabel': 'Offer', 'tone': 'bg-emerald-500'},
    {'key': 'REJECTED', 'label': 'Rejected', 'shortLabel': 'Reject', 'tone': 'bg-rose-500'},
    {'key': 'GHOSTED', 'label': 'Ghosted', 'shortLabel': 'Ghost', 'tone': 'bg-slate-400'},
]

STATUS_ALIASES = {
    'applied': 'APPLIED',
    'apply': 'APPLIED',
    'submitted': 'APPLIED',
    'online assessment': 'OA',
    'oa': 'OA',
    'assessment': 'OA',
    'phone screen': 'SCREEN',
    'screen': 'SCREEN',
    'recruiter screen': 'SCREEN',
    'recruiter call': 'SCREEN',
    'onsite': 'ONSITE',
    'onsite interview': 'ONSITE',
    'final': 'ONSITE',
    'final round': 'ONSITE',
    'offer': 'OFFER',
    'accepted': 'OFFER',
    'reject': 'REJECTED',
    'rejected': 'REJECTED',
    'declined': 'REJECTED',
    'ghosted': 'GHOSTED',
}

ROUND_TONES = ['bg-amber-400', 'bg-amber-500', 'bg-orange-500', 'bg-orange-600', 'bg-red-500']
CUSTOM_STAGE_TONES = ['bg-blue-500', 'bg-violet-500', 'bg-sky-500', 'bg-amber-500', 'bg-emerald-500']


def default_mapping_for_target(target_type):
    if target_type == GoogleSheetSyncConfig.TARGET_EVENTS:
        return EVENT_DEFAULT_MAPPING.copy()
    return APPLICATION_DEFAULT_MAPPING.copy()


def parse_google_sheet_url(sheet_url):
    parsed = urlparse(sheet_url or '')
    match = re.search(r'/spreadsheets/d/([^/?#]+)', parsed.path)
    spreadsheet_id = match.group(1) if match else ''
    gid = parse_qs(parsed.query).get('gid', [''])[0]
    return spreadsheet_id, gid


def get_service_account_email():
    info = _load_service_account_info(silent=True)
    return (info or {}).get('client_email', '')


def fetch_sheet_rows(config):
    if not config.spreadsheet_id:
        config.spreadsheet_id, parsed_gid = parse_google_sheet_url(config.sheet_url)
        if parsed_gid and not config.gid:
            config.gid = parsed_gid

    if not config.spreadsheet_id:
        raise ValidationError('Enter a valid Google Sheets link.')

    errors = []
    try:
        return _fetch_google_oauth_rows(config)
    except Exception as oauth_error:
        errors.append(f'Google OAuth error: {oauth_error}')

    try:
        return _fetch_public_csv_rows(config)
    except Exception as public_error:
        errors.append(f'Public CSV error: {public_error}')

    try:
        return _fetch_google_api_rows(config)
    except Exception as api_error:
        errors.append(f'Service account error: {api_error}')
        raise ValidationError(
            'Could not read this sheet. Connect Google for private access, share it publicly as CSV, '
            'or share it with the configured service account. '
            + ' '.join(errors)
        )


def preview_sheet(config, limit=5):
    rows = fetch_sheet_rows(config)
    header_index = max((config.header_row or 1) - 1, 0)
    if len(rows) <= header_index:
        return {'headers': [], 'rows': []}
    headers = [_clean_cell(value) for value in rows[header_index]]
    body = [_row_to_dict(headers, row) for row in rows[header_index + 1:header_index + 1 + limit]]
    return {'headers': headers, 'rows': body}


def sync_google_sheet(config, force=False):
    rows = fetch_sheet_rows(config)
    header_index = max((config.header_row or 1) - 1, 0)
    if len(rows) <= header_index:
        raise ValidationError('No header row was found in this sheet.')

    headers = [_dedupe_headers([_clean_cell(value) for value in rows[header_index]])]
    headers = headers[0]
    mapping = config.column_mapping or default_mapping_for_target(config.target_type)
    result = {
        'target_type': config.target_type,
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'errors': [],
        'scanned_rows': 0,
    }

    for offset, raw_row in enumerate(rows[header_index + 1:], start=header_index + 2):
        row = _row_to_dict(headers, raw_row)
        if not any(str(value).strip() for value in row.values()):
            result['skipped'] += 1
            continue

        result['scanned_rows'] += 1
        try:
            action = _sync_row(config, row, offset, mapping, force=force)
            result[action] += 1
        except Exception as exc:
            result['errors'].append({'row': offset, 'error': str(exc)})

    config.last_synced_at = timezone.now()
    config.last_result = result
    if result['errors']:
        config.last_status = GoogleSheetSyncConfig.STATUS_ERROR
        config.last_error = f"{len(result['errors'])} row(s) failed."
    else:
        config.last_status = GoogleSheetSyncConfig.STATUS_SUCCESS
        config.last_error = ''
    config.save(update_fields=['last_synced_at', 'last_result', 'last_status', 'last_error', 'spreadsheet_id', 'gid', 'updated_at'])
    return result


def sync_enabled_google_sheets(only_due=False, now=None):
    summary = {
        'configs': 0,
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'errors': [],
    }
    for config in GoogleSheetSyncConfig.objects.filter(enabled=True).select_related('user'):
        summary['configs'] += 1
        if only_due and not _is_sync_config_due(config, now=now):
            summary['skipped'] += 1
            continue
        try:
            result = sync_google_sheet(config)
            summary['created'] += result.get('created', 0)
            summary['updated'] += result.get('updated', 0)
            summary['skipped'] += result.get('skipped', 0)
            for row_error in result.get('errors', []):
                summary['errors'].append({'config': config.name, **row_error})
        except Exception as exc:
            config.last_synced_at = timezone.now()
            config.last_status = GoogleSheetSyncConfig.STATUS_ERROR
            config.last_error = str(exc)
            config.save(update_fields=['last_synced_at', 'last_status', 'last_error', 'updated_at'])
            summary['errors'].append({'config': config.name, 'error': str(exc)})
    return summary


def _is_sync_config_due(config, now=None):
    now = now or timezone.now()
    try:
        sync_timezone = ZoneInfo(config.sync_timezone or 'America/Los_Angeles')
    except ZoneInfoNotFoundError:
        sync_timezone = ZoneInfo('UTC')

    local_now = now.astimezone(sync_timezone)
    scheduled_time = config.sync_time or time(22, 0)
    if local_now.time() < scheduled_time:
        return False

    if not config.last_synced_at:
        return True

    last_local = config.last_synced_at.astimezone(sync_timezone)
    return not (last_local.date() == local_now.date() and last_local.time() >= scheduled_time)


def _fetch_public_csv_rows(config):
    query = {'format': 'csv'}
    if config.gid:
        query['gid'] = config.gid
    url = f"https://docs.google.com/spreadsheets/d/{config.spreadsheet_id}/export?{urlencode(query)}"
    request = Request(url, headers={'User-Agent': 'CareerHub Google Sheets Sync'})
    try:
        with urlopen(request, timeout=15) as response:
            data = response.read().decode('utf-8-sig')
    except HTTPError as exc:
        raise ValidationError(f'Google returned HTTP {exc.code}.')
    except URLError as exc:
        raise ValidationError(str(exc.reason))

    if '<html' in data[:200].lower():
        raise ValidationError('Google returned an HTML page instead of CSV.')
    return list(csv.reader(io.StringIO(data)))


def _fetch_google_api_rows(config):
    info = _load_service_account_info()
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ValidationError('Install google-api-python-client and google-auth to read private sheets.') from exc

    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'],
    )
    service = build('sheets', 'v4', credentials=credentials, cache_discovery=False)
    range_name = f"'{config.worksheet_name}'" if config.worksheet_name else 'A:ZZ'
    response = service.spreadsheets().values().get(
        spreadsheetId=config.spreadsheet_id,
        range=range_name,
        majorDimension='ROWS',
    ).execute()
    return response.get('values', [])


def _fetch_google_oauth_rows(config):
    from .google_oauth import get_google_oauth_credentials

    credentials = get_google_oauth_credentials(config.user)
    if not credentials:
        raise ValidationError('Google is not connected.')
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ValidationError('Install google-api-python-client to read private sheets.') from exc

    service = build('sheets', 'v4', credentials=credentials, cache_discovery=False)
    range_name = f"'{config.worksheet_name}'" if config.worksheet_name else 'A:ZZ'
    response = service.spreadsheets().values().get(
        spreadsheetId=config.spreadsheet_id,
        range=range_name,
        majorDimension='ROWS',
    ).execute()
    return response.get('values', [])


def _load_service_account_info(silent=False):
    raw = (
        os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        or os.environ.get('GOOGLE_SERVICE_ACCOUNT_INFO')
        or os.environ.get('GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON')
        or ''
    ).strip()
    if not raw:
        if silent:
            return None
        raise ValidationError('No Google service account credentials are configured.')

    try:
        if raw.startswith('{'):
            return json.loads(raw)
        decoded = base64.b64decode(raw).decode('utf-8')
        return json.loads(decoded)
    except Exception as exc:
        if silent:
            return None
        raise ValidationError('Google service account credentials are not valid JSON.') from exc


def _sync_row(config, row, row_number, mapping, force=False):
    payload = _mapped_payload(row, mapping)
    external_key = _external_key(payload, row_number)
    row_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    payload['_user'] = config.user
    tracked = GoogleSheetSyncRow.objects.filter(config=config, external_key=external_key).first()
    if tracked and tracked.row_hash == row_hash and not force and not _needs_application_date_backfill(config, payload, tracked):
        return 'skipped'

    with transaction.atomic():
        if config.target_type == GoogleSheetSyncConfig.TARGET_EVENTS:
            instance, created = _upsert_event(config, payload, tracked)
            local_type = 'availability.Event'
        else:
            instance, created = _upsert_application(config, payload, tracked)
            local_type = 'career.Application'

        GoogleSheetSyncRow.objects.update_or_create(
            config=config,
            external_key=external_key,
            defaults={
                'row_number': row_number,
                'row_hash': row_hash,
                'local_object_type': local_type,
                'local_object_id': instance.id,
            },
        )
    return 'created' if created else 'updated'


def _mapped_payload(row, mapping):
    payload = {}
    for field, column in mapping.items():
        if not column:
            continue
        payload[field] = _clean_cell(row.get(column, ''))
    return payload


def _external_key(payload, row_number):
    explicit = _clean_cell(payload.get('external_id', ''))
    return explicit or f'row:{row_number}'


def _needs_application_date_backfill(config, payload, tracked):
    if config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS or not tracked:
        return False
    if 'date_applied' in payload:
        return False
    application = Application.objects.filter(id=tracked.local_object_id, user=config.user).only('date_applied').first()
    return bool(application and not application.date_applied)


def _upsert_application(config, payload, tracked):
    company_name = payload.get('company_name') or payload.get('company') or ''
    role_title = payload.get('role_title') or ''
    if not company_name or not role_title:
        raise ValidationError('Application rows need Company and Role values.')

    defaults = _application_defaults_from_payload(payload, apply_create_defaults=tracked is None)
    company, _ = Company.objects.get_or_create(user=config.user, name=company_name)

    if tracked:
        application = Application.objects.filter(id=tracked.local_object_id, user=config.user).first()
        if application:
            application.company = company
            application.role_title = role_title
            if 'date_applied' not in payload and not application.date_applied:
                defaults['date_applied'] = timezone.localtime(tracked.created_at).date()
            for field, value in defaults.items():
                setattr(application, field, value)
            application.save()
            return application, False

    existing_application = _find_existing_application_by_sheet_identity(config, company, role_title, payload, defaults)
    if existing_application:
        for field, value in defaults.items():
            setattr(existing_application, field, value)
        existing_application.save()
        return existing_application, False

    application = Application.objects.create(
        user=config.user,
        company=company,
        role_title=role_title,
        **defaults,
    )
    return application, True


def _find_existing_application_by_sheet_identity(config, company, role_title, payload, defaults):
    identity_fields = ['salary_range', 'location', 'office_location', 'job_link']
    filters = {
        'user': config.user,
        'company': company,
        'role_title': role_title,
    }
    for field in identity_fields:
        if field in payload:
            filters[field] = defaults.get(field)
    return Application.objects.filter(**filters).order_by('id').first()


def _application_defaults_from_payload(payload, apply_create_defaults=False):
    defaults = {}
    if apply_create_defaults:
        defaults['status'] = 'APPLIED'
        defaults['date_applied'] = timezone.localdate()

    if 'status' in payload:
        defaults['status'] = _normalize_application_status(payload.get('status'), payload.get('_user'))
    if 'job_link' in payload:
        defaults['job_link'] = payload.get('job_link') or None
    if 'salary_range' in payload:
        defaults['salary_range'] = payload.get('salary_range') or ''
    if 'location' in payload:
        defaults['location'] = payload.get('location') or ''
    if 'office_location' in payload:
        defaults['office_location'] = payload.get('office_location') or ''
    if 'date_applied' in payload:
        parsed_date = _parse_date(payload.get('date_applied'))
        if parsed_date:
            defaults['date_applied'] = parsed_date
    if 'notes' in payload:
        defaults['notes'] = payload.get('notes') or ''
    return defaults


def _normalize_application_status(value, user):
    cleaned = _clean_status_text(value)
    if not cleaned:
        return 'APPLIED'

    round_match = re.search(r'\b(\d+)(?:st|nd|rd|th)?\s+round\b', cleaned)
    if round_match:
        round_number = int(round_match.group(1))
        key = f'ROUND_{round_number}'
        _ensure_application_stage(user, key, _round_label(round_number), f'R{round_number}', _round_tone(round_number))
        return key

    alias_key = STATUS_ALIASES.get(cleaned)
    if alias_key:
        _ensure_known_stage(user, alias_key)
        return alias_key

    key = re.sub(r'[^A-Z0-9]+', '_', cleaned.upper()).strip('_') or 'APPLIED'
    label = _title_status(cleaned)
    _ensure_application_stage(user, key, label, _short_label(label), _custom_stage_tone(user))
    return key


def _clean_status_text(value):
    text = _clean_cell(value)
    text = re.sub(r'\s*\([^)]*\)', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()


def _ensure_known_stage(user, key):
    known = {stage['key']: stage for stage in DEFAULT_APPLICATION_STAGES}
    stage = known.get(key)
    if stage:
        _ensure_application_stage(user, stage['key'], stage['label'], stage['shortLabel'], stage['tone'])


def _ensure_application_stage(user, key, label, short_label, tone):
    if not user:
        return
    settings_profile, _ = UserSettings.objects.get_or_create(user=user)
    stages = settings_profile.application_stages or [stage.copy() for stage in DEFAULT_APPLICATION_STAGES]
    if any(stage.get('key') == key for stage in stages):
        if not settings_profile.application_stages:
            settings_profile.application_stages = stages
            settings_profile.save(update_fields=['application_stages', 'updated_at'])
        return
    stages.append({'key': key, 'label': label, 'shortLabel': short_label, 'tone': tone})
    settings_profile.application_stages = stages
    settings_profile.save(update_fields=['application_stages', 'updated_at'])


def _round_label(round_number):
    if 10 <= round_number % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(round_number % 10, 'th')
    return f'{round_number}{suffix} Round'


def _round_tone(round_number):
    return ROUND_TONES[min(max(round_number, 1), len(ROUND_TONES)) - 1]


def _custom_stage_tone(user):
    if not user:
        return CUSTOM_STAGE_TONES[0]
    settings_profile = UserSettings.objects.filter(user=user).first()
    existing_count = len(settings_profile.application_stages or []) if settings_profile else 0
    return CUSTOM_STAGE_TONES[existing_count % len(CUSTOM_STAGE_TONES)]


def _title_status(value):
    return ' '.join(part.capitalize() for part in value.split())


def _short_label(label):
    words = [word for word in re.split(r'\s+', label) if word]
    if not words:
        return label[:6]
    if len(words) == 1:
        return words[0][:8]
    return ''.join(word[0].upper() for word in words[:3])


def _upsert_event(config, payload, tracked):
    name = payload.get('name') or ''
    event_date = _parse_date(payload.get('date'))
    start_time = payload.get('start_time') or ''
    end_time = payload.get('end_time') or ''
    if not name or not event_date or not start_time or not end_time:
        raise ValidationError('Event rows need Name, Date, Start Time, and End Time values.')

    category = None
    category_name = payload.get('category') or ''
    if category_name:
        category, _ = EventCategory.objects.get_or_create(
            user=config.user,
            name=category_name,
            defaults={'color': '#2563eb', 'icon': 'calendar'},
        )

    defaults = {
        'name': name,
        'date': event_date,
        'start_time': start_time,
        'end_time': end_time,
        'timezone': _timezone_value(payload.get('timezone')),
        'location_type': _location_type_value(payload.get('location_type')),
        'location': payload.get('location') or '',
        'meeting_link': payload.get('meeting_link') or '',
        'category': category,
        'notes': payload.get('notes') or '',
    }

    if tracked:
        event = Event.objects.filter(id=tracked.local_object_id, user=config.user).first()
        if event:
            for field, value in defaults.items():
                setattr(event, field, value)
            event.save()
            return event, False

    event, created = Event.objects.update_or_create(
        user=config.user,
        name=name,
        date=event_date,
        start_time=start_time,
        defaults=defaults,
    )
    return event, created


def _row_to_dict(headers, row):
    return {
        header: _clean_cell(row[index]) if index < len(row) else ''
        for index, header in enumerate(headers)
        if header
    }


def _dedupe_headers(headers):
    seen = {}
    result = []
    for header in headers:
        if not header:
            result.append('')
            continue
        count = seen.get(header, 0)
        seen[header] = count + 1
        result.append(header if count == 0 else f'{header} {count + 1}')
    return result


def _clean_cell(value):
    if value is None:
        return ''
    return str(value).strip()


def _clean_choice(value, default=''):
    value = _clean_cell(value)
    return value.upper().replace('-', '_').replace(' ', '_') if value else default


def _timezone_value(value):
    value = _clean_choice(value, default='PT')
    return value if value in {'PT', 'ET', 'CT', 'MT'} else 'PT'


def _location_type_value(value):
    value = _clean_choice(value, default='virtual').lower()
    aliases = {
        'in_person': 'in_person',
        'in-person': 'in_person',
        'in person': 'in_person',
        'onsite': 'in_person',
        'virtual': 'virtual',
        'remote': 'virtual',
        'hybrid': 'hybrid',
    }
    return aliases.get(value, 'virtual')


def _parse_date(value):
    value = _clean_cell(value)
    if not value:
        return None
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%B %d, %Y', '%b %d, %Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    try:
        from django.utils.dateparse import parse_date

        parsed = parse_date(value)
        if parsed:
            return parsed
    except Exception:
        pass
    try:
        serial = Decimal(value)
    except (InvalidOperation, ValueError):
        serial = None
    if serial is not None:
        base = datetime(1899, 12, 30)
        return (base + timedelta(days=int(serial))).date()
    raise ValidationError(f'Could not parse date "{value}".')
