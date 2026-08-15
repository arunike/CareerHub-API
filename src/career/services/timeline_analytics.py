import statistics
from collections import defaultdict
from datetime import date

from django.db.models import Prefetch
from django.utils import timezone

from availability.models import UserSettings
from career.models import Application, ApplicationTimelineEntry, GoogleSheetSyncRow
from career.services.application_stats import _group_location
from career.services.google_sheets import DEFAULT_APPLICATION_STAGES


# Reaching any of these means an offer was made, whatever happened next. Declining one
# still counts as having received it, and accepting one certainly does — nothing here
# stays in the pipeline.
OFFER_STATUSES = {'OFFER', 'ACCEPTED', 'OFFER_REJECTED'}
# A settled application is not "stale in stage"; it is finished. ACCEPTED was missing,
# so an offer accepted two years ago was reported as 740 days stuck in a stage.
TERMINAL_STATUSES = OFFER_STATUSES | {'REJECTED', 'GHOSTED', 'REMOVED_FROM_SHEET'}
NON_INTERVIEW_STATUSES = {'APPLIED', 'OFFER', 'REJECTED', 'GHOSTED'}
# Reaching one of these is not the company replying to you. Everything else is.
NON_RESPONSE_STATUSES = {'APPLIED', 'GHOSTED', 'REMOVED_FROM_SHEET'}

# How long after applying a reply arrived. The last bucket is open-ended because the point
# is to find where replies stop, not to chart the tail.
RESPONSE_BUCKETS = (
    ('0-7 days', 0, 7),
    ('8-14 days', 8, 14),
    ('15-30 days', 15, 30),
    ('31-60 days', 31, 60),
    ('60+ days', 61, None),
)
# A stage median built from one or two transitions is an anecdote, not a typical duration,
# so it is reported with its sample size and only used as a comparison above this.
MIN_DURATION_SAMPLE = 3


def _percentile(values, fraction):
    """Nearest-rank percentile. Small samples are the norm here, so interpolating between
    two neighbours would invent precision the data does not have."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _rate_rows(counter):
    """Segment rows with the sample size kept alongside the rate.

    A 50% rate off two applications is noise, and the caller cannot tell without `total`,
    so it is always returned rather than left for the UI to infer."""
    rows = [
        {
            'name': name,
            'total': data['total'],
            'responded': data['responded'],
            'response_rate': round(data['responded'] / data['total'], 6) if data['total'] else 0,
        }
        for name, data in counter.items()
        if data['total']
    ]
    return sorted(rows, key=lambda row: (-row['response_rate'], -row['total'], row['name']))


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


def build_application_timeline_analytics(user, year=None):
    # Offers from two years ago drag an all-time rate towards zero, so the whole report is
    # scoped the same way the rest of the app scopes by year: on when you applied.
    queryset = Application.objects.filter(user=user)
    if year:
        queryset = queryset.filter(date_applied__year=year)

    applications = list(
        queryset
        .select_related('company', 'offer')
        .only(
            'id',
            'company__name',
            'role_title',
            'status',
            'date_applied',
            'created_at',
            'level',
            'employment_type',
            'location',
            'office_location',
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
    days_to_response = []
    # Response rate, not offer rate: with a handful of offers every offer-rate breakdown is
    # noise, while a reply is common enough for the segments to mean something.
    response_by_source = defaultdict(lambda: {'total': 0, 'responded': 0})
    response_by_location = defaultdict(lambda: {'total': 0, 'responded': 0})
    response_by_level = defaultdict(lambda: {'total': 0, 'responded': 0})
    # Days spent in a stage before moving on, per stage, so "stalled" can mean something
    # different for a phone screen than for an onsite.
    durations_by_stage = defaultdict(list)
    open_without_response = []

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

        # A reply is any movement past applied. Status alone misses an application that was
        # interviewed and then rejected, so the timeline counts too.
        response_dates = [
            _entry_date(entry) for entry in entries if entry.stage not in NON_RESPONSE_STATUSES
        ]
        has_responded = bool(response_dates) or application.status not in NON_RESPONSE_STATUSES
        if response_dates:
            days = _days_between(applied_date, min(response_dates))
            if days is not None:
                days_to_response.append(days)
        elif application.status not in TERMINAL_STATUSES:
            # Still open and still silent: how long it has been waiting decides whether it is
            # merely slow or already past the point where replies stop arriving.
            waiting = _days_between(applied_date, today)
            if waiting is not None:
                open_without_response.append(waiting)

        segment_source = source_map.get(application.id)
        for counter, key in (
            (response_by_source, segment_source['name'] if segment_source else 'Manual / Not synced'),
            (response_by_location, _group_location(application.office_location, application.location)),
            (response_by_level, (application.level or '').strip() or 'Unspecified'),
        ):
            counter[key]['total'] += 1
            if has_responded:
                counter[key]['responded'] += 1

        # Time each stage took before the next one, walked in the order the stages are
        # configured so a skipped stage does not read as an instant transition.
        dated_progress = [
            (index, _entry_date(entry_by_stage[key]))
            for index, key in enumerate(funnel_stage_keys)
            if key in entry_by_stage and _entry_date(entry_by_stage[key])
        ]
        for (index, stage_date_from), (_, stage_date_to) in zip(dated_progress, dated_progress[1:]):
            elapsed = _days_between(stage_date_from, stage_date_to)
            if elapsed is not None:
                durations_by_stage[funnel_stage_keys[index]].append(elapsed)

        source = source_map.get(application.id)
        company_name = application.company.name
        is_offer = application.status in OFFER_STATUSES or hasattr(application, 'offer')
        if source:
            source_key = source['name']
            offer_by_source[source_key]['total'] += 1
            if is_offer:
                offer_by_source[source_key]['offers'] += 1

        offer_by_company[company_name]['total'] += 1
        if is_offer:
            offer_by_company[company_name]['offers'] += 1
            # When the offer arrived, which is what the timeline records. The Offer row's
            # created_at is when it was typed into CareerHub: backfilling a 2024 offer in
            # 2026 reported it as a 545-day wait and dragged the average to 7x reality.
            offer_dates = [_entry_date(entry) for entry in entries if entry.stage in OFFER_STATUSES]
            offer_date = min(offer_dates) if offer_dates else None
            if offer_date is None and getattr(application, 'offer', None) and application.offer.created_at:
                offer_date = timezone.localtime(application.offer.created_at).date()
            days = _days_between(applied_date, offer_date)
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
            # 6dp, not 4: at the bottom of a large funnel the interesting digits are past
            # the fourth. 2 offers in 806 is 0.002481, which 4dp flattened to 0.0025 and
            # left the display a rounding step away from reading 0%.
            'conversion_rate': round(reached_by_stage[key] / total_applications, 6) if total_applications else 0,
        }
        for key in ordered_stage_keys
        if reached_by_stage[key] or current_by_stage[key]
    ]

    # Terminal outcomes are results, not pipeline progress, so they are reported
    # separately from stage_conversion rather than appearing as funnel steps.
    TERMINAL_STAGE_KEYS = ('OFFER', 'ACCEPTED', 'REJECTED', 'GHOSTED', 'OFFER_REJECTED')
    outcomes = [
        {
            'key': key,
            'label': _stage_label(key, stage_map),
            'count': current_by_stage[key],
        }
        for key in TERMINAL_STAGE_KEYS
        if current_by_stage[key]
    ]

    pipeline_stages = [
        row for row in stage_conversion if row['key'] not in {'REJECTED', 'GHOSTED', 'REMOVED_FROM_SHEET', 'OFFER_REJECTED', 'ACCEPTED'}
    ]

    # Anything that got past the first pipeline stage counts as a real response.
    responded_count = 0
    for row in pipeline_stages[1:]:
        responded_count = max(responded_count, row['reached_count'])

    ghosted_count = current_by_stage['GHOSTED']

    # The steepest consecutive drop is usually the most actionable number here.
    biggest_drop = None
    for previous, current in zip(pipeline_stages, pipeline_stages[1:]):
        lost = previous['reached_count'] - current['reached_count']
        if lost > 0 and (biggest_drop is None or lost > biggest_drop['lost']):
            biggest_drop = {
                'from_label': previous['label'],
                'to_label': current['label'],
                'lost': lost,
            }

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

    offer_count = sum(1 for row in offer_by_company.values() for _ in range(row['offers']))
    offer_sample_size = len(days_to_offer)
    average_days_to_offer = round(sum(days_to_offer) / offer_sample_size, 1) if offer_sample_size else None

    # --- How long replies take, and when to stop waiting for one ---
    response_sample = len(days_to_response)
    response_buckets = []
    running = 0
    for label, low, high in RESPONSE_BUCKETS:
        count = sum(
            1 for days in days_to_response if days >= low and (high is None or days <= high)
        )
        running += count
        response_buckets.append(
            {
                'label': label,
                'max_days': high,
                'count': count,
                'cumulative_share': round(running / response_sample, 6) if response_sample else 0,
            }
        )

    # The point where replies effectively stop: 90% of the ones ever received had arrived.
    # Taken from the actual distribution rather than snapped to a bucket edge, which rounded
    # 32 days up to 60 and made the cutoff a month more forgiving than the data supports.
    followup_days = _percentile(days_to_response, 0.9)

    stage_durations = [
        {
            'key': key,
            'label': _stage_label(key, stage_map),
            'median_days': round(statistics.median(values), 1),
            'p90_days': _percentile(values, 0.9),
            'sample_size': len(values),
        }
        for key in funnel_stage_keys
        for values in [durations_by_stage.get(key) or []]
        if values
    ]
    typical_by_stage = {
        row['key']: row['median_days']
        for row in stage_durations
        if row['sample_size'] >= MIN_DURATION_SAMPLE
    }

    for row in stale_in_stage:
        typical = typical_by_stage.get(row['status'])
        row['typical_days'] = typical
        # None when the stage has no history to compare against, rather than a fabricated 0.
        row['days_over_typical'] = (
            round(row['days_in_stage'] - typical, 1) if typical is not None else None
        )

    return {
        'average_time_to_interview_days': average_days,
        'time_to_interview_sample_size': sample_size,
        'average_days_to_offer': average_days_to_offer,
        'days_to_offer_sample_size': offer_sample_size,
        'response_time_buckets': response_buckets,
        'response_time_sample_size': response_sample,
        'median_days_to_response': _percentile(days_to_response, 0.5),
        'p90_days_to_response': _percentile(days_to_response, 0.9),
        'suggested_followup_days': followup_days,
        'min_duration_sample': MIN_DURATION_SAMPLE,
        # Open, silent, and already past the follow-up cutoff: almost certainly not coming.
        'silent_past_followup_count': (
            sum(1 for days in open_without_response if days > followup_days)
            if followup_days is not None
            else 0
        ),
        'open_without_response_count': len(open_without_response),
        'response_rate_by_source': _rate_rows(response_by_source),
        'response_rate_by_location': _rate_rows(response_by_location),
        'response_rate_by_level': _rate_rows(response_by_level),
        'stage_durations': stage_durations,
        'stage_conversion': stage_conversion,
        'total_applications': total_applications,
        'offer_count': offer_count,
        'offer_rate': round(offer_count / total_applications * 100, 1) if total_applications else 0,
        'outcomes': outcomes,
        'responded_count': responded_count,
        'response_rate': round(responded_count / total_applications * 100, 1) if total_applications else 0,
        'ghosted_count': ghosted_count,
        'ghost_rate': round(ghosted_count / total_applications * 100, 1) if total_applications else 0,
        'biggest_drop': biggest_drop,
        'stale_threshold_days': threshold_days,
        'stale_in_stage': sorted(stale_in_stage, key=lambda row: row['days_in_stage'], reverse=True),
        'offer_rate_by_source': rate_rows(offer_by_source),
        'offer_rate_by_company': rate_rows(offer_by_company)[:10],
    }
