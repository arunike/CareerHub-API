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
from .google_sheet_rows import _current_user_date, _datetime_in_user_date


def _sync_application_timeline_from_status(application, diff):
    status_change = diff.get('status') if diff else None
    if not status_change:
        return

    old_status, new_status = _status_change_values(status_change)
    sync_date = _current_user_date(application.user)
    _prune_later_round_timeline_entries(application, old_status, new_status)
    for stage in _timeline_stages_for_status_change(
        application.user,
        old_status,
        new_status,
    ):
        _ensure_application_timeline_entry(
            application,
            stage,
            sync_date,
        )


def _prune_later_round_timeline_entries(application, old_status, new_status):
    old_round = _round_number_from_stage_key(old_status)
    new_round = _round_number_from_stage_key(new_status)
    if not old_round or not new_round or new_round >= old_round:
        return

    later_round_keys = [f'ROUND_{round_number}' for round_number in range(new_round + 1, old_round + 1)]
    later_entries = ApplicationTimelineEntry.objects.filter(
        user=application.user,
        application=application,
        stage__in=later_round_keys,
        deleted_by_user_at__isnull=True,
    )
    for entry in later_entries:
        has_user_content = bool(
            entry.display_title
            or entry.notes
            or entry.event_date_is_user_override
            or entry.notes_is_user_override
        )
        if has_user_content:
            entry.hidden_by_sync_at = timezone.now()
            entry.save(update_fields=['hidden_by_sync_at', 'updated_at'])
        else:
            entry.delete()


def _repair_tracked_application_timeline_from_sync_history(
    config,
    tracked,
    timeline_repair_cache=None,
    applications_by_id=None,
    timeline_stage_cache=None,
):
    if not getattr(config, 'id', None) or config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS:
        return

    if applications_by_id is not None:
        application = applications_by_id.get(tracked.local_object_id)
    else:
        application = Application.objects.filter(
            id=tracked.local_object_id,
            user=config.user,
        ).first()
    if not application:
        return

    if timeline_repair_cache is None:
        timeline_repair_cache = _timeline_repair_cache_from_sync_runs(config)
    stage_dates = dict(timeline_repair_cache.get(application.id, {}))
    fallback_date = _datetime_in_user_date(tracked.last_seen_at, config.user)
    for stage in _timeline_stages_for_existing_status(application):
        stage_dates.setdefault(stage, fallback_date)

    for stage, event_date in stage_dates.items():
        stage_round = _round_number_from_stage_key(stage)
        current_round = _round_number_from_stage_key(application.status)
        if stage_round and current_round and stage_round > current_round:
            continue
        if timeline_stage_cache is not None and stage in timeline_stage_cache.get(application.id, set()):
            continue
        _ensure_application_timeline_entry(application, stage, event_date)
        if timeline_stage_cache is not None and event_date:
            timeline_stage_cache.setdefault(application.id, set()).add(stage)


def _timeline_repair_cache_from_sync_runs(config):
    if not getattr(config, 'id', None) or config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS:
        return {}

    stage_dates_by_application = {}
    runs = GoogleSheetSyncRun.objects.filter(config=config).order_by('started_at', 'id')
    for run in runs:
        event_date = _datetime_in_user_date(run.started_at, config.user)
        for change in run.changes or []:
            application_id = change.get('local_object_id')
            if not application_id:
                continue
            status_change = (change.get('diff') or {}).get('status')
            if not status_change:
                continue
            old_status, new_status = _status_change_values(status_change)
            for stage in _timeline_stages_for_status_change(
                config.user,
                old_status,
                new_status,
            ):
                stage_dates_by_application.setdefault(application_id, {}).setdefault(stage, event_date)
    return stage_dates_by_application


def _timeline_stage_dates_from_sync_runs(config, application):
    return _timeline_repair_cache_from_sync_runs(config).get(application.id, {})


def _timeline_stages_for_existing_status(application):
    current_round = _round_number_from_stage_key(application.status)
    if not current_round:
        return [application.status] if application.status else []

    existing_rounds = [
        round_number
        for round_number in (
            _round_number_from_stage_key(stage)
            for stage in application.timeline_entries.values_list('stage', flat=True)
        )
        if round_number
    ]
    start_round = min(existing_rounds) if existing_rounds else 1
    stages = []
    for round_number in range(start_round, current_round + 1):
        key = f'ROUND_{round_number}'
        _ensure_application_stage(
            application.user,
            key,
            _round_label(round_number),
            f'R{round_number}',
            _round_tone(round_number),
        )
        stages.append(key)
    return stages


def _ensure_application_timeline_entry(application, stage, event_date, notes=None):
    defaults = {'event_date': event_date}
    if notes is not None:
        defaults['notes'] = notes
    entry, created = ApplicationTimelineEntry.objects.get_or_create(
        user=application.user,
        application=application,
        stage=stage,
        defaults=defaults,
    )
    if entry.deleted_by_user_at:
        return entry
    update_fields = []
    if entry.hidden_by_sync_at:
        entry.hidden_by_sync_at = None
        update_fields.append('hidden_by_sync_at')
    if (
        not created
        and not entry.event_date_is_user_override
        and entry.event_date is None
        and event_date
    ):
        entry.event_date = event_date
        update_fields.append('event_date')
    if (
        not created
        and not entry.notes_is_user_override
        and notes is not None
        and entry.notes != notes
    ):
        entry.notes = notes
        update_fields.append('notes')
    if update_fields:
        entry.save(update_fields=[*update_fields, 'updated_at'])


def _timeline_stages_for_status_change(user, old_status, new_status):
    if not new_status:
        return []

    old_round = _round_number_from_stage_key(old_status)
    new_round = _round_number_from_stage_key(new_status)
    if old_round and new_round and new_round > old_round:
        stages = []
        for round_number in range(old_round, new_round + 1):
            key = f'ROUND_{round_number}'
            _ensure_application_stage(
                user,
                key,
                _round_label(round_number),
                f'R{round_number}',
                _round_tone(round_number),
            )
            stages.append(key)
        return stages

    return [new_status]


def _status_change_values(status_change):
    old_status = status_change.get('old')
    if old_status is None:
        old_status = status_change.get('from')
    if old_status is None:
        old_status = status_change.get('before')

    new_status = status_change.get('new')
    if new_status is None:
        new_status = status_change.get('to')
    if new_status is None:
        new_status = status_change.get('after')

    return old_status, new_status


def _round_number_from_stage_key(stage):
    match = re.fullmatch(r'ROUND_(\d+)', str(stage or ''))
    return int(match.group(1)) if match else None
