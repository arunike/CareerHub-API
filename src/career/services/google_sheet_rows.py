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


def _current_user_date(user):
    settings_profile = UserSettings.objects.filter(user=user).first() if user else None
    timezone_name = settings_profile.primary_timezone if settings_profile else 'America/Los_Angeles'
    try:
        return timezone.now().astimezone(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError:
        return timezone.localdate()


def _datetime_in_user_date(value, user):
    settings_profile = UserSettings.objects.filter(user=user).first() if user else None
    timezone_name = settings_profile.primary_timezone if settings_profile else 'America/Los_Angeles'
    try:
        return timezone.localtime(value, ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError:
        return timezone.localtime(value).date()


def _mapped_payload(row, mapping):
    payload = {}
    for field, column in mapping.items():
        if not column:
            continue
        payload[field] = _clean_cell(row.get(column, ''))
    return payload


def _external_key(payload, row_number):
    explicit = _clean_cell(payload.get('external_id', ''))
    if explicit:
        return explicit
    identity_parts = [
        payload.get('company_name') or payload.get('company') or '',
        payload.get('role_title') or '',
        payload.get('salary_range') or '',
        _normalize_location_string(payload.get('location')),
        _normalize_location_string(payload.get('office_location')),
        payload.get('job_link') or '',
    ]
    if identity_parts[0] and identity_parts[1]:
        raw_identity = json.dumps([_clean_cell(part).lower() for part in identity_parts])
        return f'identity:{hashlib.sha256(raw_identity.encode("utf-8")).hexdigest()[:24]}'
    return f'row:{row_number}'


def _tracked_rows_by_external_key(config):
    if not getattr(config, 'id', None):
        return {}
    return {
        row.external_key: row
        for row in GoogleSheetSyncRow.objects.filter(config=config)
    }


def _applications_by_tracked_row(config, tracked_rows):
    if config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS:
        return {}
    application_ids = {
        row.local_object_id
        for row in tracked_rows
        if row.local_object_type == 'career.Application' and row.local_object_id
    }
    if not application_ids:
        return {}
    return {
        application.id: application
        for application in Application.objects.filter(
            id__in=application_ids,
            user=config.user,
        ).select_related('company')
    }


def _timeline_stage_cache(config, applications_by_id):
    if config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS or not applications_by_id:
        return {}
    cache = {application_id: set() for application_id in applications_by_id}
    for entry in ApplicationTimelineEntry.objects.filter(
        user=config.user,
        application_id__in=applications_by_id.keys(),
        event_date__isnull=False,
        deleted_by_user_at__isnull=True,
        hidden_by_sync_at__isnull=True,
    ).only('application_id', 'stage'):
        cache.setdefault(entry.application_id, set()).add(entry.stage)
    return cache


def _needs_application_date_backfill(config, payload, tracked, applications_by_id=None):
    if config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS or not tracked:
        return False
    if payload.get('date_applied'):
        return False
    if applications_by_id is not None:
        application = applications_by_id.get(tracked.local_object_id)
        return bool(application and not application.date_applied)
    application = Application.objects.filter(id=tracked.local_object_id, user=config.user).only('date_applied').first()
    return bool(application and not application.date_applied)


def _needs_application_source_restore(config, tracked, applications_by_id=None):
    if config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS or not tracked:
        return False
    if applications_by_id is not None:
        application = applications_by_id.get(tracked.local_object_id)
        return bool(application and application.source_removed_at)
    return Application.objects.filter(
        id=tracked.local_object_id,
        user=config.user,
        source_removed_at__isnull=False,
    ).exists()


def _find_existing_application_by_sheet_identity(config, company, role_title, payload, defaults):
    identity_fields = ['salary_range', 'location', 'office_location', 'job_link']
    filters = {
        'user': config.user,
        'company': company,
        'role_title': role_title,
    }
    for field in identity_fields:
        if field in payload:
            if field in {'location', 'office_location'}:
                filters[f'{field}__in'] = _location_lookup_values(defaults.get(field))
            else:
                filters[field] = defaults.get(field)
    return Application.objects.filter(**filters).order_by('id').first()


def _application_defaults_from_payload(payload, apply_create_defaults=False, ensure_stages=True, stage_events=None):
    defaults = {}
    if apply_create_defaults:
        defaults['status'] = 'APPLIED'
        defaults['date_applied'] = _current_user_date(payload.get('_user'))

    if 'status' in payload:
        defaults['status'] = _normalize_application_status(
            payload.get('status'),
            payload.get('_user'),
            ensure_stage=ensure_stages,
            stage_events=stage_events,
        )
    if 'job_link' in payload:
        defaults['job_link'] = payload.get('job_link') or None
    if 'salary_range' in payload:
        defaults['salary_range'] = payload.get('salary_range') or ''
    if 'location' in payload:
        defaults['location'] = _normalize_location_string(payload.get('location'))
    if 'office_location' in payload:
        defaults['office_location'] = _normalize_location_string(payload.get('office_location'))
    if 'date_applied' in payload:
        parsed_date = _parse_date(payload.get('date_applied'))
        if parsed_date:
            defaults['date_applied'] = parsed_date
    if 'notes' in payload:
        defaults['notes'] = payload.get('notes') or ''
    return defaults
