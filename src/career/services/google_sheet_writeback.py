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


def _apply_field_updates(application, company, role_title, defaults, strategies, is_new=False):
    diff = {}
    
    if application.company_id != company.id:
        if is_new or strategies.get('company_name', 'always') == 'always':
            diff['company_name'] = {'old': application.company.name if application.company else None, 'new': company.name}
            application.company = company
            
    if application.role_title != role_title:
        if is_new or strategies.get('role_title', 'always') == 'always':
            diff['role_title'] = {'old': application.role_title, 'new': role_title}
            application.role_title = role_title
            
    for field, new_value in defaults.items():
        old_value = getattr(application, field, None)
        if old_value == new_value:
            continue
            
        strategy = strategies.get(field, 'always')
        if is_new:
            strategy = 'always'
        if field in {'source_removed_at', 'source_removed_delete_after', 'source_removed_previous_status'}:
            strategy = 'always'
        if field == 'status' and application.source_removed_at:
            strategy = 'always'
            
        should_update = False
        if strategy == 'always':
            should_update = True
        elif strategy == 'if_empty':
            if old_value is None or old_value == '':
                should_update = True
        
        if should_update:
            # We cast to string for diffing to avoid JSON serialization issues with Decimals/Dates
            old_str = str(old_value) if old_value is not None else None
            new_str = str(new_value) if new_value is not None else None
            diff[field] = {'old': old_str, 'new': new_str}
            setattr(application, field, new_value)
            
    return diff


def _restore_source_removed_defaults(application, defaults):
    if not application.source_removed_at:
        return defaults
    restored = {
        **defaults,
        'source_removed_at': None,
        'source_removed_delete_after': None,
        'source_removed_previous_status': '',
    }
    if 'status' not in restored and application.source_removed_previous_status:
        restored['status'] = application.source_removed_previous_status
    return restored


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
        return event, False, {}

    event, created = Event.objects.update_or_create(
        user=config.user,
        name=name,
        date=event_date,
        start_time=start_time,
        defaults=defaults,
    )
    return event, created, {}
