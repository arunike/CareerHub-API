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


def _handle_missing_sheet_rows(config, seen_external_keys, mapping):
    result = {
        'archived': 0,
        'deleted': 0,
        'warnings': [],
        'history': [],
        'changes': [],
    }
    if config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS:
        return result
    if config.missing_row_strategy != GoogleSheetSyncConfig.MISSING_ROW_ARCHIVE_THEN_DELETE:
        return result

    now = timezone.now()
    delete_after = now + timedelta(days=config.missing_row_delete_after_days or 30)
    has_external_id_mapping = bool((mapping or {}).get('external_id'))
    missing_rows = GoogleSheetSyncRow.objects.filter(
        config=config,
        local_object_type='career.Application',
    ).exclude(
        external_key__in=seen_external_keys,
    ).exclude(
        external_key__startswith='row:',
    )
    if has_external_id_mapping:
        missing_rows = missing_rows.exclude(external_key__startswith='identity:')
    else:
        missing_rows = missing_rows.filter(external_key__startswith='identity:')

    for tracked in missing_rows:
        application = Application.objects.filter(id=tracked.local_object_id, user=config.user).select_related('company').first()
        if not application:
            tracked.delete()
            continue

        if application.source_removed_at:
            if application.source_removed_delete_after and application.source_removed_delete_after <= now:
                if application.is_locked:
                    result['warnings'].append({
                        'row': tracked.row_number,
                        'local_object_id': application.id,
                        'message': f'{application.company.name} {application.role_title} is locked and was not permanently deleted.',
                    })
                    continue
                history = _history_entry(
                    'source_deleted',
                    tracked.row_number,
                    {'company_name': application.company.name, 'role_title': application.role_title},
                    f'{application.company.name} {application.role_title}: permanently deleted after missing from the sheet for {config.missing_row_delete_after_days or 30} day(s).',
                    local_object_id=application.id,
                )
                result['history'].append(history)
                result['changes'].append({
                    'action': 'deleted',
                    'row_number': tracked.row_number,
                    'diff': {},
                    'history_id': None,
                    'local_object_id': application.id,
                })
                application.delete()
                tracked.delete()
                result['deleted'] += 1
            continue

        _ensure_application_stage(
            config.user,
            REMOVED_FROM_SHEET_STAGE['key'],
            REMOVED_FROM_SHEET_STAGE['label'],
            REMOVED_FROM_SHEET_STAGE['shortLabel'],
            REMOVED_FROM_SHEET_STAGE['tone'],
        )
        previous_status = application.status if application.status != REMOVED_FROM_SHEET_STATUS else ''
        before_label = _application_stage_label(config.user, application.status)
        application.source_removed_previous_status = previous_status
        application.source_removed_at = now
        application.source_removed_delete_after = delete_after
        application.status = REMOVED_FROM_SHEET_STATUS
        application.save(update_fields=[
            'status',
            'source_removed_at',
            'source_removed_delete_after',
            'source_removed_previous_status',
            'updated_at',
        ])
        history = _history_entry(
            'source_archived',
            tracked.row_number,
            {'company_name': application.company.name, 'role_title': application.role_title},
            f'{application.company.name} {application.role_title}: archived because it is no longer present in the sheet. It will be deleted after {application.source_removed_delete_after.date().isoformat()} unless the row reappears.',
            field='status',
            before=previous_status,
            after=REMOVED_FROM_SHEET_STATUS,
            local_object_id=application.id,
        )
        result['history'].append(history)
        result['changes'].append({
            'action': 'archived',
            'row_number': tracked.row_number,
            'diff': {
                'status': {'old': before_label, 'new': REMOVED_FROM_SHEET_STAGE['label']},
            },
            'history_id': None,
            'local_object_id': application.id,
        })
        result['archived'] += 1

    return result
