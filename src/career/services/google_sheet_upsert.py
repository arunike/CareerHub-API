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
from .google_sheet_fetching import (  # noqa: F401
    _fetch_google_api_rows,
    _fetch_google_oauth_rows,
    _fetch_public_csv_rows,
    _load_service_account_info,
    get_service_account_email,
    parse_google_sheet_url,
)
from .google_sheet_rows import (
    _application_defaults_from_payload,
    _applications_by_tracked_row,
    _current_user_date,
    _datetime_in_user_date,
    _external_key,
    _find_existing_application_by_sheet_identity,
    _mapped_payload,
    _needs_application_date_backfill,
    _needs_application_source_restore,
    _timeline_stage_cache,
    _tracked_rows_by_external_key,
)
from .google_sheet_timeline import (  # noqa: F401
    _ensure_application_timeline_entry,
    _prune_later_round_timeline_entries,
    _repair_tracked_application_timeline_from_sync_history,
    _round_number_from_stage_key,
    _status_change_values,
    _sync_application_timeline_from_status,
    _timeline_repair_cache_from_sync_runs,
    _timeline_stage_dates_from_sync_runs,
    _timeline_stages_for_existing_status,
    _timeline_stages_for_status_change,
)
from .google_sheet_writeback import (
    _apply_field_updates,
    _restore_source_removed_defaults,
    _upsert_event,
)


def _review_application_row(config, row, row_number, mapping, seen_identities, force=False):
    payload = _mapped_payload(row, mapping)
    external_key = _external_key(payload, row_number)
    row_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    payload['_user'] = config.user
    tracked = GoogleSheetSyncRow.objects.filter(config=config, external_key=external_key).first()
    if (
        tracked
        and tracked.row_hash == row_hash
        and not force
        and not _needs_application_date_backfill(config, payload, tracked)
        and not _needs_application_source_restore(config, tracked)
    ):
        return None

    company_name = payload.get('company_name') or payload.get('company') or ''
    role_title = payload.get('role_title') or ''
    if not company_name or not role_title:
        raise ValidationError('Application rows need Company and Role values.')

    defaults = _application_defaults_from_payload(
        payload,
        apply_create_defaults=tracked is None,
        ensure_stages=False,
    )
    application = None
    duplicate_row = None
    duplicate_candidate = None
    incoming_fields = _incoming_application_fields(company_name, role_title, payload, defaults)

    if tracked:
        application = Application.objects.filter(id=tracked.local_object_id, user=config.user).select_related('company').first()
        if application and not payload.get('date_applied') and not application.date_applied:
            defaults['date_applied'] = _datetime_in_user_date(tracked.created_at, config.user)
    else:
        company = Company.objects.filter(user=config.user, name=company_name).first()
        if company:
            application = _find_existing_application_by_sheet_identity(config, company, role_title, payload, defaults)
            if application:
                duplicate_candidate = {
                    'local_object_id': application.id,
                    'row': None,
                    'fields': _application_snapshot(application),
                }
        identity = _sheet_identity(company_name, role_title, payload, defaults)
        seen_match = seen_identities.get(identity)
        duplicate_row = seen_match.get('row') if seen_match else None
        if seen_match and not duplicate_candidate:
            duplicate_candidate = {
                'local_object_id': None,
                'row': seen_match.get('row'),
                'fields': seen_match.get('fields') or {},
            }
        seen_identities.setdefault(identity, {'row': row_number, 'fields': incoming_fields})

    changes = _application_changes(application, company_name, role_title, defaults) if application else {}
    if application and not changes and not force:
        return None

    if not tracked and (application or duplicate_row):
        action = 'possible_duplicate'
    elif application and 'status' in changes:
        action = 'status_change'
    elif application:
        action = 'update'
    else:
        action = 'create'

    item = {
        'id': _review_item_id(config, external_key, row_hash, action),
        'row': row_number,
        'external_key': external_key,
        'action': action,
        'company_name': company_name,
        'role_title': role_title,
        'status': defaults.get('status') or '',
        'salary_range': defaults.get('salary_range') or payload.get('salary_range') or '',
        'location': defaults.get('location') or payload.get('location') or '',
        'job_link': defaults.get('job_link') or payload.get('job_link') or '',
        'local_object_id': application.id if application else None,
        'changes': changes,
        'duplicate_row': duplicate_row,
        'duplicate_candidate': duplicate_candidate,
        'incoming_fields': incoming_fields,
        'title': f'{company_name} - {role_title}',
        'detail': _review_detail(action, application, changes, duplicate_row),
    }
    return item


def _build_history_context(config, payload, tracked, row_number, duplicate_resolution='merge'):
    if config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS:
        return {}

    company_name = payload.get('company_name') or payload.get('company') or ''
    role_title = payload.get('role_title') or ''
    context = {
        'row_number': row_number,
        'tracked': bool(tracked),
        'date_backfilled': False,
        'matched_duplicate': False,
        'duplicate_resolution': duplicate_resolution,
        'created_stages': [],
        'before': None,
        'changes': {},
    }

    application = None
    if tracked:
        application = Application.objects.filter(id=tracked.local_object_id, user=config.user).select_related('company').first()
    else:
        preview_defaults = _application_defaults_from_payload(
            payload,
            apply_create_defaults=True,
            ensure_stages=False,
        )
        company = Company.objects.filter(user=config.user, name=company_name).first()
        if company:
            application = _find_existing_application_by_sheet_identity(config, company, role_title, payload, preview_defaults)
            context['matched_duplicate'] = bool(application)
            if application and duplicate_resolution in {'keep_separate', 'intentional_duplicate'}:
                application = None

    if application:
        context['before'] = _application_snapshot(application)
        preview_defaults = _application_defaults_from_payload(
            payload,
            apply_create_defaults=tracked is None,
            ensure_stages=False,
        )
        if tracked and not payload.get('date_applied') and not application.date_applied:
            preview_defaults['date_applied'] = _datetime_in_user_date(tracked.created_at, config.user)
            context['date_backfilled'] = True
        context['changes'] = _application_changes(application, company_name, role_title, preview_defaults)

    return context


def _upsert_application(
    config,
    payload,
    tracked,
    history_context=None,
    duplicate_resolution='merge',
    timeline_repair_cache=None,
):
    company_name = payload.get('company_name') or payload.get('company') or ''
    role_title = payload.get('role_title') or ''
    if not company_name or not role_title:
        raise ValidationError('Application rows need Company and Role values.')

    history_context = history_context if history_context is not None else {}
    defaults = _application_defaults_from_payload(
        payload,
        apply_create_defaults=tracked is None,
        stage_events=history_context.setdefault('created_stages', []),
    )
    company, _ = Company.objects.get_or_create(user=config.user, name=company_name)
    strategies = getattr(config, 'overwrite_strategies', {}) or {}

    if tracked:
        application = Application.objects.filter(id=tracked.local_object_id, user=config.user).first()
        if application:
            if not payload.get('date_applied') and not application.date_applied:
                defaults['date_applied'] = _datetime_in_user_date(tracked.created_at, config.user)
            defaults = _restore_source_removed_defaults(application, defaults)
            diff = _apply_field_updates(application, company, role_title, defaults, strategies, is_new=False)
            if diff:
                application.save()
                _sync_application_timeline_from_status(application, diff)
                if tracked:
                    _repair_tracked_application_timeline_from_sync_history(
                        config,
                        tracked,
                        timeline_repair_cache=timeline_repair_cache,
                    )
                return application, False, diff
            if tracked:
                _repair_tracked_application_timeline_from_sync_history(
                    config,
                    tracked,
                    timeline_repair_cache=timeline_repair_cache,
                )
            return application, False, {}

    existing_application = None
    if duplicate_resolution not in {'keep_separate', 'intentional_duplicate'}:
        existing_application = _find_existing_application_by_sheet_identity(config, company, role_title, payload, defaults)
    if existing_application:
        if not payload.get('date_applied') and not existing_application.date_applied:
            defaults['date_applied'] = _datetime_in_user_date(tracked.created_at, config.user) if tracked else _current_user_date(config.user)
        defaults = _restore_source_removed_defaults(existing_application, defaults)
        diff = _apply_field_updates(existing_application, company, role_title, defaults, strategies, is_new=False)
        if diff:
            existing_application.save()
            _sync_application_timeline_from_status(existing_application, diff)
            if tracked:
                _repair_tracked_application_timeline_from_sync_history(
                    config,
                    tracked,
                    timeline_repair_cache=timeline_repair_cache,
                )
            return existing_application, False, diff
        if tracked:
            _repair_tracked_application_timeline_from_sync_history(
                config,
                tracked,
                timeline_repair_cache=timeline_repair_cache,
            )
        return existing_application, False, {}

    if not payload.get('date_applied'):
        defaults['date_applied'] = _datetime_in_user_date(tracked.created_at, config.user) if tracked else _current_user_date(config.user)

    application = Application(
        user=config.user,
        company=company,
        role_title=role_title,
    )
    diff = _apply_field_updates(application, company, role_title, defaults, strategies, is_new=True)
    application.save()
    _sync_application_timeline_from_status(application, diff)
    return application, True, diff
