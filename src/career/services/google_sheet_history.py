import hashlib

from django.utils import timezone

from career.models import Application
from .google_sheet_stages import _application_stage_label
from .sheet_parsing import clean_cell as _clean_cell


def _review_item_id(config, external_key, row_hash, action):
    raw = f'{config.id}:{external_key}:{row_hash}:{action}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def _review_summary_key(action):
    return {
        'create': 'new_applications',
        'status_change': 'status_changes',
        'possible_duplicate': 'possible_duplicates',
        'update': 'updates',
    }.get(action, 'updates')


def _review_detail(action, application, changes, duplicate_row):
    if action == 'create':
        return 'New application detected.'
    if action == 'possible_duplicate':
        if application:
            return 'Matches an existing application. Approving will update/link that record instead of creating another duplicate.'
        return f'Looks like a duplicate of sheet row {duplicate_row}.'
    if action == 'status_change':
        change = changes.get('status') or {}
        return f"Status changes from {change.get('from') or 'blank'} to {change.get('to') or 'blank'}."
    if changes:
        return f"{len(changes)} field change(s) detected."
    return 'No changes detected.'


def _application_changes(application, company_name, role_title, defaults):
    if not application:
        return {}
    desired = {
        'company_name': company_name,
        'role_title': role_title,
        **defaults,
    }
    current = {
        'company_name': application.company.name,
        'role_title': application.role_title,
        'status': application.status,
        'job_link': application.job_link or '',
        'salary_range': application.salary_range or '',
        'location': application.location or '',
        'office_location': application.office_location or '',
        'date_applied': application.date_applied.isoformat() if application.date_applied else '',
        'notes': application.notes or '',
    }
    changes = {}
    for field, next_value in desired.items():
        current_value = current.get(field, '')
        if hasattr(next_value, 'isoformat'):
            next_value = next_value.isoformat()
        if next_value is None:
            next_value = ''
        if str(current_value) != str(next_value):
            changes[field] = {'from': current_value, 'to': next_value}
    return changes


def _sheet_identity(company_name, role_title, payload, defaults):
    parts = [company_name, role_title]
    for field in ['salary_range', 'location', 'office_location', 'job_link']:
        if field in payload:
            parts.append(defaults.get(field) or '')
    return tuple(_clean_cell(part).lower() for part in parts)


def _incoming_application_fields(company_name, role_title, payload, defaults):
    fields = {
        'company_name': company_name,
        'role_title': role_title,
    }
    for field in ['status', 'salary_range', 'location', 'office_location', 'job_link', 'date_applied', 'notes']:
        if field in defaults:
            value = defaults.get(field)
        else:
            value = payload.get(field, '')
        if hasattr(value, 'isoformat'):
            value = value.isoformat()
        fields[field] = value or ''
    return fields


def _application_snapshot(application):
    return {
        'company_name': application.company.name,
        'role_title': application.role_title,
        'status': application.status,
        'job_link': application.job_link or '',
        'salary_range': application.salary_range or '',
        'location': application.location or '',
        'office_location': application.office_location or '',
        'date_applied': application.date_applied.isoformat() if application.date_applied else '',
        'notes': application.notes or '',
    }


def _history_for_sync_result(action, row_number, payload, instance, context):
    if not isinstance(instance, Application):
        return [_history_entry(action, row_number, payload, f'{instance.name} synced.')]

    history = []
    base_payload = {
        **payload,
        'company_name': instance.company.name,
        'role_title': instance.role_title,
    }

    if action == 'created':
        history.append(_history_entry(
            'created',
            row_number,
            base_payload,
            f'{instance.company.name} {instance.role_title}: new application created.',
            local_object_id=instance.id,
        ))

    if context.get('matched_duplicate') and context.get('duplicate_resolution') in {'keep_separate', 'intentional_duplicate'}:
        history.append(_history_entry(
            'intentional_duplicate_created' if context.get('duplicate_resolution') == 'intentional_duplicate' else 'duplicate_kept_separate',
            row_number,
            base_payload,
            f'{instance.company.name} {instance.role_title}: duplicate kept as a separate application.',
            local_object_id=instance.id,
        ))
    elif context.get('matched_duplicate'):
        history.append(_history_entry(
            'duplicate_matched',
            row_number,
            base_payload,
            f'{instance.company.name} {instance.role_title}: duplicate skipped because company, role, pay, and location matched an existing application.',
            local_object_id=instance.id,
        ))

    for field, change in (context.get('changes') or {}).items():
        if field == 'status':
            before = _application_stage_label(instance.user, change.get('from'))
            after = _application_stage_label(instance.user, change.get('to'))
            history.append(_history_entry(
                'status_changed',
                row_number,
                base_payload,
                f'{instance.company.name} {instance.role_title}: {before} -> {after}.',
                field='status',
                before=change.get('from') or '',
                after=change.get('to') or '',
                local_object_id=instance.id,
            ))
        elif field == 'date_applied' and context.get('date_backfilled'):
            history.append(_history_entry(
                'date_applied_backfilled',
                row_number,
                base_payload,
                f'{instance.company.name} {instance.role_title}: date applied backfilled to {change.get("to") or "blank"}.',
                field='date_applied',
                before=change.get('from') or '',
                after=change.get('to') or '',
                local_object_id=instance.id,
            ))
        else:
            history.append(_history_entry(
                'field_changed',
                row_number,
                base_payload,
                f'{instance.company.name} {instance.role_title}: {field.replace("_", " ")} changed from {change.get("from") or "blank"} to {change.get("to") or "blank"}.',
                field=field,
                before=change.get('from') or '',
                after=change.get('to') or '',
                local_object_id=instance.id,
            ))

    for stage in context.get('created_stages') or []:
        history.append(_history_entry(
            'custom_stage_created',
            row_number,
            base_payload,
            f'New application timeline stage created: {stage.get("label")}.',
            field='status',
            after=stage.get('key') or '',
            local_object_id=instance.id,
        ))

    if action == 'updated' and not history:
        history.append(_history_entry(
            'updated',
            row_number,
            base_payload,
            f'{instance.company.name} {instance.role_title}: synced with no visible field changes.',
            local_object_id=instance.id,
        ))

    return history


def _history_entry(kind, row_number, payload, message, field='', before='', after='', local_object_id=None):
    return {
        'type': kind,
        'row': row_number,
        'company_name': payload.get('company_name') or payload.get('company') or '',
        'role_title': payload.get('role_title') or '',
        'field': field,
        'before': before,
        'after': after,
        'message': message,
        'local_object_id': local_object_id,
        'created_at': timezone.now().isoformat(),
    }
