from collections import defaultdict
from datetime import date

from django.db.models import Prefetch
from django.utils import timezone

from availability.models import UserSettings
from career.models import Application, ApplicationTimelineEntry, GoogleSheetSyncRow
from career.services.google_sheets import DEFAULT_APPLICATION_STAGES


TERMINAL_STATUSES = {'OFFER', 'REJECTED', 'GHOSTED'}
NON_INTERVIEW_STATUSES = {'APPLIED', 'OFFER', 'REJECTED', 'GHOSTED'}


def _stage_settings_for_user(user):
    try:
        profile = user.availability_settings_profile
    except UserSettings.DoesNotExist:
        profile = None

    stages = profile.application_stages if profile and profile.application_stages else DEFAULT_APPLICATION_STAGES
    stage_map = {stage.get('key'): stage for stage in stages if stage.get('key')}
    return stages, stage_map


def _stage_label(stage_key, stage_map):
    stage = stage_map.get(stage_key) or {}
    return stage.get('label') or stage.get('shortLabel') or stage_key.replace('_', ' ').title()


def _entry_date(entry):
    if entry.event_date:
        return entry.event_date
    return timezone.localtime(entry.created_at).date()


def _application_start_date(application):
    if application.date_applied:
        return application.date_applied
    return timezone.localtime(application.created_at).date()


def _days_between(start, end):
    if not start or not end:
        return None
    delta = (end - start).days
    return delta if delta >= 0 else None


def _source_by_application_id(user):
    rows = (
        GoogleSheetSyncRow.objects.filter(
            config__user=user,
            config__target_type='APPLICATIONS',
            local_object_type='career.Application',
        )
        .select_related('config')
        .only(
            'config_id',
            'local_object_id',
            'last_seen_at',
            'config__name',
            'config__worksheet_name',
        )
        .order_by('local_object_id', '-last_seen_at')
    )

    source_map = {}
    for row in rows:
        if row.local_object_id not in source_map:
            source_map[row.local_object_id] = {
                'id': row.config_id,
                'name': row.config.name,
                'worksheet': row.config.worksheet_name,
            }
    return source_map


def build_application_timeline_analytics(user):
    applications = list(
        Application.objects.filter(user=user)
        .select_related('company', 'offer')
        .only(
            'id',
            'company__name',
            'role_title',
            'status',
            'date_applied',
            'created_at',
            'offer__created_at',
        )
        .prefetch_related(
            Prefetch(
                'timeline_entries',
                queryset=ApplicationTimelineEntry.objects.filter(
                    deleted_by_user_at__isnull=True,
                    hidden_by_sync_at__isnull=True,
                ).only(
                    'application_id',
                    'stage',
                    'event_date',
                    'created_at',
                ),
                to_attr='analytics_timeline_entries',
            )
        )
        .order_by('company__name', 'role_title')
    )
    stages, stage_map = _stage_settings_for_user(user)
    source_map = _source_by_application_id(user)
    today = timezone.localdate()

    try:
        threshold_days = int(user.availability_settings_profile.ghosting_threshold_days)
    except (UserSettings.DoesNotExist, TypeError, ValueError):
        threshold_days = 14

    reached_by_stage = defaultdict(int)
    current_by_stage = defaultdict(int)
    time_to_interview_days = []
    days_to_offer = []
    stale_in_stage = []
    offer_by_source = defaultdict(lambda: {'total': 0, 'offers': 0})
    offer_by_company = defaultdict(lambda: {'total': 0, 'offers': 0})

    # Identify non-negative funnel stage keys in their defined order
    funnel_stage_keys = [
        s.get('key')
        for s in stages
        if s.get('key') and s.get('key') not in {'REJECTED', 'GHOSTED', 'REMOVED_FROM_SHEET'}
    ]

    for application in applications:
        entries = list(getattr(application, 'analytics_timeline_entries', []))
        entry_by_stage = {entry.stage: entry for entry in entries}
        reached_stages = {entry.stage for entry in entries}
        reached_stages.add(application.status)
        if application.date_applied or application.created_at:
            reached_stages.add('APPLIED')

        # Backfill preceding stages in the positive funnel progression
        reached_indices = [
            i for i, key in enumerate(funnel_stage_keys)
            if key in reached_stages
        ]
        if reached_indices:
            max_idx = max(reached_indices)
            for key in funnel_stage_keys[:max_idx + 1]:
                reached_stages.add(key)

        for stage in reached_stages:
            reached_by_stage[stage] += 1
            if stage not in stage_map:
                stage_map[stage] = {'key': stage, 'label': _stage_label(stage, stage_map), 'shortLabel': stage}

        current_by_stage[application.status] += 1

        applied_date = _entry_date(entry_by_stage['APPLIED']) if 'APPLIED' in entry_by_stage else _application_start_date(application)
        interview_dates = [
            _entry_date(entry)
            for entry in entries
            if entry.stage not in NON_INTERVIEW_STATUSES
        ]
        if interview_dates:
            days = _days_between(applied_date, min(interview_dates))
            if days is not None:
                time_to_interview_days.append(days)

        source = source_map.get(application.id)
        company_name = application.company.name
        is_offer = application.status == 'OFFER' or hasattr(application, 'offer')
        if source:
            source_key = source['name']
            offer_by_source[source_key]['total'] += 1
            if is_offer:
                offer_by_source[source_key]['offers'] += 1

        offer_by_company[company_name]['total'] += 1
        if is_offer:
            offer_by_company[company_name]['offers'] += 1
            if hasattr(application, 'offer') and application.offer and application.date_applied:
                offer_created_date = timezone.localtime(application.offer.created_at).date() if application.offer.created_at else None
                if offer_created_date:
                    days = _days_between(application.date_applied, offer_created_date)
                    if days is not None:
                        days_to_offer.append(days)

        if application.status not in TERMINAL_STATUSES:
            current_entry = entry_by_stage.get(application.status)
            stage_date = _entry_date(current_entry) if current_entry else _application_start_date(application)
            days_in_stage = _days_between(stage_date, today)
            if days_in_stage is not None and days_in_stage >= threshold_days:
                stale_in_stage.append(
                    {
                        'application_id': application.id,
                        'company': company_name,
                        'role_title': application.role_title,
                        'status': application.status,
                        'status_label': _stage_label(application.status, stage_map),
                        'days_in_stage': days_in_stage,
                        'last_stage_date': stage_date.isoformat() if isinstance(stage_date, date) else None,
                        'source': source['name'] if source else 'Manual / Not synced',
                    }
                )

    total_applications = len(applications)
    ordered_stage_keys = []
    for stage in stages:
        key = stage.get('key')
        if key and key not in ordered_stage_keys:
            ordered_stage_keys.append(key)
    for key in sorted(set(reached_by_stage) | set(current_by_stage)):
        if key not in ordered_stage_keys:
            ordered_stage_keys.append(key)

    stage_conversion = [
        {
            'key': key,
            'label': _stage_label(key, stage_map),
            'reached_count': reached_by_stage[key],
            'current_count': current_by_stage[key],
            'conversion_rate': round(reached_by_stage[key] / total_applications, 4) if total_applications else 0,
        }
        for key in ordered_stage_keys
        if reached_by_stage[key] or current_by_stage[key]
    ]

    def rate_rows(grouped):
        rows = []
        for name, values in grouped.items():
            total = values['total']
            offers = values['offers']
            rows.append(
                {
                    'name': name,
                    'total': total,
                    'offers': offers,
                    'offer_rate': round(offers / total, 4) if total else 0,
                }
            )
        return sorted(rows, key=lambda row: (row['offer_rate'], row['offers'], row['total']), reverse=True)

    sample_size = len(time_to_interview_days)
    average_days = round(sum(time_to_interview_days) / sample_size, 1) if sample_size else None

    offer_sample_size = len(days_to_offer)
    average_days_to_offer = round(sum(days_to_offer) / offer_sample_size, 1) if offer_sample_size else None

    return {
        'average_time_to_interview_days': average_days,
        'time_to_interview_sample_size': sample_size,
        'average_days_to_offer': average_days_to_offer,
        'days_to_offer_sample_size': offer_sample_size,
        'stage_conversion': stage_conversion,
        'stale_threshold_days': threshold_days,
        'stale_in_stage': sorted(stale_in_stage, key=lambda row: row['days_in_stage'], reverse=True),
        'offer_rate_by_source': rate_rows(offer_by_source),
        'offer_rate_by_company': rate_rows(offer_by_company)[:10],
    }
