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
from .google_sheet_missing_rows import _handle_missing_sheet_rows
from .google_sheet_upsert import (  # noqa: F401
    _build_history_context,
    _review_application_row,
    _upsert_application,
)


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
    run = GoogleSheetSyncRun.objects.create(
        config=config,
        status=GoogleSheetSyncRun.STATUS_ERROR, # Default to error until completion
        started_at=timezone.now()
    )

    try:
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
            'archived': 0,
            'deleted': 0,
            'skipped': 0,
            'errors': [],
            'warnings': [],
            'history': [],
            'scanned_rows': 0,
        }

        changes_list = []
        timeline_repair_cache = _timeline_repair_cache_from_sync_runs(config)
        tracked_rows_by_key = _tracked_rows_by_external_key(config)
        applications_by_id = _applications_by_tracked_row(config, tracked_rows_by_key.values())
        timeline_stage_cache = _timeline_stage_cache(config, applications_by_id)
        seen_external_keys = set()

        for offset, raw_row in enumerate(rows[header_index + 1:], start=header_index + 2):
            row = _row_to_dict(headers, raw_row)
            if not any(str(value).strip() for value in row.values()):
                result['skipped'] += 1
                continue

            result['scanned_rows'] += 1
            try:
                key_payload = _mapped_payload(row, mapping)
                external_key = _external_key(key_payload, offset)
                duplicate_key_in_sheet = external_key in seen_external_keys
                seen_external_keys.add(external_key)
                action, history, diff = _sync_row_with_history(
                    config,
                    row,
                    offset,
                    mapping,
                    force=force or duplicate_key_in_sheet,
                    timeline_repair_cache=timeline_repair_cache,
                    tracked_rows_by_key=tracked_rows_by_key,
                    applications_by_id=applications_by_id,
                    timeline_stage_cache=timeline_stage_cache,
                )
                result[action] += 1
                result['history'].extend(history)
                if action in ['created', 'updated']:
                    first_history = history[0] if history else {}
                    changes_list.append({
                        'action': action,
                        'row_number': offset,
                        'diff': diff,
                        'history_id': None,
                        'local_object_id': first_history.get('local_object_id') if config.target_type == GoogleSheetSyncConfig.TARGET_APPLICATIONS else None,
                    })
            except Exception as exc:
                result['errors'].append({'row': offset, 'error': str(exc)})

        missing_result = _handle_missing_sheet_rows(config, seen_external_keys, mapping)
        result['archived'] += missing_result['archived']
        result['deleted'] += missing_result['deleted']
        result['missing_from_sheet'] = missing_result['archived'] + missing_result['deleted']
        result['warnings'].extend(missing_result['warnings'])
        result['history'].extend(missing_result['history'])
        changes_list.extend(missing_result['changes'])

        run.status = GoogleSheetSyncRun.STATUS_SUCCESS if not result['errors'] else GoogleSheetSyncRun.STATUS_ERROR
        run.summary = {k: v for k, v in result.items() if k != 'history'}
        run.changes = changes_list
        if result['errors']:
            run.error_details = f"{len(result['errors'])} row(s) failed."
            
        config.last_synced_at = timezone.now()
        config.last_result = result
        if result['errors']:
            config.last_status = GoogleSheetSyncConfig.STATUS_ERROR
            config.last_error = f"{len(result['errors'])} row(s) failed."
        else:
            config.last_status = GoogleSheetSyncConfig.STATUS_SUCCESS
            config.last_error = ''
        config.save(update_fields=['last_synced_at', 'last_result', 'last_status', 'last_error', 'spreadsheet_id', 'gid', 'updated_at'])
        
    except Exception as e:
        run.status = GoogleSheetSyncRun.STATUS_ERROR
        run.error_details = str(e)
        
        config.last_synced_at = timezone.now()
        config.last_status = GoogleSheetSyncConfig.STATUS_ERROR
        config.last_error = str(e)
        config.save(update_fields=['last_synced_at', 'last_status', 'last_error', 'updated_at'])
        raise e
    finally:
        run.completed_at = timezone.now()
        run.save()

    return result

def rollback_sync_run(run_id, user):
    run = GoogleSheetSyncRun.objects.select_related('config').filter(id=run_id, config__user=user).first()
    if not run:
        raise ValidationError('Sync run not found.')
    if run.status == GoogleSheetSyncRun.STATUS_ROLLED_BACK:
        raise ValidationError('This run is already rolled back.')
        
    config = run.config
    changes = run.changes
    
    with transaction.atomic():
        # Iterate in reverse to safely undo
        for change in reversed(changes):
            local_id = change.get('local_object_id')
            if not local_id:
                continue
                
            if config.target_type == GoogleSheetSyncConfig.TARGET_APPLICATIONS:
                app = Application.objects.filter(id=local_id, user=user).first()
                if not app:
                    continue
                    
                if change['action'] == 'created':
                    app.delete()
                elif change['action'] == 'archived':
                    app.status = app.source_removed_previous_status or 'APPLIED'
                    app.source_removed_at = None
                    app.source_removed_delete_after = None
                    app.source_removed_previous_status = ''
                    app.save(update_fields=[
                        'status',
                        'source_removed_at',
                        'source_removed_delete_after',
                        'source_removed_previous_status',
                        'updated_at',
                    ])
                elif change['action'] == 'updated' and change.get('diff'):
                    # Revert diffs
                    for field, values in change['diff'].items():
                        old_val = values.get('old')
                        
                        # Company requires special handling since it's an FK
                        if field == 'company_name' and old_val is not None:
                            company, _ = Company.objects.get_or_create(user=user, name=old_val)
                            app.company = company
                        elif field != 'company_name':
                            # Best effort type casting back
                            setattr(app, field, old_val)
                    app.save()

        run.status = GoogleSheetSyncRun.STATUS_ROLLED_BACK
        run.save()


def build_import_review(config, force=False):
    if config.target_type != GoogleSheetSyncConfig.TARGET_APPLICATIONS:
        raise ValidationError('Import review is currently available for application syncs.')

    rows = fetch_sheet_rows(config)
    header_index = max((config.header_row or 1) - 1, 0)
    if len(rows) <= header_index:
        raise ValidationError('No header row was found in this sheet.')

    headers = _dedupe_headers([_clean_cell(value) for value in rows[header_index]])
    mapping = config.column_mapping or default_mapping_for_target(config.target_type)
    review = {
        'target_type': config.target_type,
        'summary': {
            'new_applications': 0,
            'status_changes': 0,
            'possible_duplicates': 0,
            'updates': 0,
            'unchanged': 0,
            'errors': 0,
        },
        'items': [],
        'errors': [],
        'scanned_rows': 0,
    }
    seen_identities = {}

    for offset, raw_row in enumerate(rows[header_index + 1:], start=header_index + 2):
        row = _row_to_dict(headers, raw_row)
        if not any(str(value).strip() for value in row.values()):
            continue
        review['scanned_rows'] += 1
        try:
            item = _review_application_row(config, row, offset, mapping, seen_identities, force=force)
        except Exception as exc:
            review['summary']['errors'] += 1
            review['errors'].append({'row': offset, 'error': str(exc)})
            continue
        if item:
            review['items'].append(item)
            review['summary'][_review_summary_key(item['action'])] += 1

    return review


def apply_import_review(config, approved_item_ids, duplicate_resolutions=None, force=False):
    approved_item_ids = set(approved_item_ids or [])
    duplicate_resolutions = duplicate_resolutions or {}
    review = build_import_review(config, force=force)
    rows = fetch_sheet_rows(config)
    header_index = max((config.header_row or 1) - 1, 0)
    headers = _dedupe_headers([_clean_cell(value) for value in rows[header_index]])
    mapping = config.column_mapping or default_mapping_for_target(config.target_type)
    approved_by_id = {item['id']: item for item in review['items'] if item['id'] in approved_item_ids}
    result = {
        'target_type': config.target_type,
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'rejected': max(len(review['items']) - len(approved_by_id), 0),
        'errors': list(review.get('errors', [])),
        'history': [],
        'scanned_rows': review.get('scanned_rows', 0),
        'review': review['summary'],
    }

    row_numbers = {item['row'] for item in approved_by_id.values()}
    for offset, raw_row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if offset not in row_numbers:
            continue
        row = _row_to_dict(headers, raw_row)
        try:
            approved_item = next((item for item in approved_by_id.values() if item['row'] == offset), {})
            resolution = duplicate_resolutions.get(approved_item.get('id'), 'merge')
            action, history, _diff = _sync_row_with_history(
                config,
                row,
                offset,
                mapping,
                force=force,
                duplicate_resolution=resolution,
            )
            result[action] += 1
            result['history'].extend(history)
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
        'archived': 0,
        'deleted': 0,
        'missing_from_sheet': 0,
        'skipped': 0,
        'errors': [],
        'warnings': [],
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
            summary['archived'] += result.get('archived', 0)
            summary['deleted'] += result.get('deleted', 0)
            summary['missing_from_sheet'] += result.get('missing_from_sheet', 0)
            summary['skipped'] += result.get('skipped', 0)
            for row_error in result.get('errors', []):
                summary['errors'].append({'config': config.name, **row_error})
            for row_warning in result.get('warnings', []):
                summary['warnings'].append({'config': config.name, **row_warning})
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


def _sync_row(config, row, row_number, mapping, force=False):
    action, _history, _diff = _sync_row_with_history(config, row, row_number, mapping, force=force)
    return action


def _sync_row_with_history(
    config,
    row,
    row_number,
    mapping,
    force=False,
    duplicate_resolution='merge',
    timeline_repair_cache=None,
    tracked_rows_by_key=None,
    applications_by_id=None,
    timeline_stage_cache=None,
):
    payload = _mapped_payload(row, mapping)
    external_key = _external_key(payload, row_number)
    row_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    payload['_user'] = config.user
    if tracked_rows_by_key is not None:
        tracked = tracked_rows_by_key.get(external_key)
    else:
        tracked = GoogleSheetSyncRow.objects.filter(config=config, external_key=external_key).first()
    if (
        tracked
        and tracked.row_hash == row_hash
        and not force
        and not _needs_application_date_backfill(
            config,
            payload,
            tracked,
            applications_by_id=applications_by_id,
        )
        and not _needs_application_source_restore(config, tracked, applications_by_id=applications_by_id)
    ):
        _repair_tracked_application_timeline_from_sync_history(
            config,
            tracked,
            timeline_repair_cache=timeline_repair_cache,
            applications_by_id=applications_by_id,
            timeline_stage_cache=timeline_stage_cache,
        )
        return 'skipped', [_history_entry('skipped', row_number, payload, 'No changes detected since the last sync.')], {}

    history_context = _build_history_context(config, payload, tracked, row_number, duplicate_resolution=duplicate_resolution)

    with transaction.atomic():
        if config.target_type == GoogleSheetSyncConfig.TARGET_EVENTS:
            instance, created, diff = _upsert_event(config, payload, tracked)
            local_type = 'availability.Event'
        else:
            instance, created, diff = _upsert_application(
                config,
                payload,
                tracked,
                history_context=history_context,
                duplicate_resolution=duplicate_resolution,
                timeline_repair_cache=timeline_repair_cache,
            )
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
    action = 'created' if created else 'updated'
    history = _history_for_sync_result(action, row_number, payload, instance, history_context)
    return action, history, diff


