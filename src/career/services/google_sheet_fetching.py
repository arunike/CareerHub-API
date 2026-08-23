import base64
import csv
import hashlib
import io
import json
import math
import os
import re
from datetime import datetime
from datetime import timedelta
from datetime import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from availability.models import Event, EventCategory, UserSettings
from career.models import (
    Application,
    ApplicationTimelineEntry,
    Company,
    GoogleSheetSyncConfig,
    GoogleSheetSyncRow,
    GoogleSheetSyncRun,
)
from .sheet_parsing import (
    clean_cell as _clean_cell,
    dedupe_headers as _dedupe_headers,
    location_lookup_values as _location_lookup_values,
    location_type_value as _location_type_value,
    normalize_location_string as _normalize_location_string,
    parse_date as _parse_date,
    row_to_dict as _row_to_dict,
    timezone_value as _timezone_value,
)
from .google_sheet_constants import (
    APPLICATION_DEFAULT_MAPPING,
    CUSTOM_STAGE_TONES,
    DEFAULT_APPLICATION_STAGES,
    EVENT_DEFAULT_MAPPING,
    REMOVED_FROM_SHEET_STAGE,
    REMOVED_FROM_SHEET_STATUS,
    ROUND_TONES,
    STATUS_ALIASES,
    default_mapping_for_target,
)
from .google_sheet_stages import (
    _application_stage_label,
    _clean_status_text,
    _custom_stage_tone,
    _ensure_application_stage,
    _ensure_known_stage,
    _generated_round_tone,
    _normalize_application_status,
    _oklch_to_hex,
    _round_label,
    _round_tone,
    _short_label,
    _title_status,
)
from .google_sheet_history import (
    _application_changes,
    _application_snapshot,
    _history_entry,
    _history_for_sync_result,
    _incoming_application_fields,
    _review_detail,
    _review_item_id,
    _review_summary_key,
    _sheet_identity,
)


def parse_google_sheet_url(sheet_url):
    parsed = urlparse(sheet_url or '')
    match = re.search(r'/spreadsheets/d/([^/?#]+)', parsed.path)
    spreadsheet_id = match.group(1) if match else ''
    gid = parse_qs(parsed.query).get('gid', [''])[0]
    return spreadsheet_id, gid


def get_service_account_email():
    info = _load_service_account_info(silent=True)
    return (info or {}).get('client_email', '')


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
