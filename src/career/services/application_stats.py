"""Dashboard aggregates for the applications list."""

from collections import defaultdict
from datetime import date, datetime

from django.db.models import Count, Q
from django.utils import timezone

INACTIVE_STATUSES = {'APPLIED', 'REJECTED', 'GHOSTED', 'ACCEPTED', 'REMOVED_FROM_SHEET'}
RESPONDED_EXCLUDE_STATUSES = {'APPLIED', 'GHOSTED', 'REMOVED_FROM_SHEET'}
# An offer counts once made: accepting moves the status and would zero the offer rate.
OFFER_STATUSES = {'OFFER', 'ACCEPTED', 'OFFER_REJECTED'}

AGE_BUCKETS = ('Last 7 days', '8-30 days', '31-90 days', '90+ days', 'Undated')

# Fields the dashboard depends on; an all-blank one is reported as unavailable.
COMPLETENESS_FIELDS = (
    ('level', 'Level', 'compare response rates by seniority'),
    ('office_location', 'Office location', 'group locations precisely instead of by free text'),
    ('salary_range', 'Salary range', 'compare advertised pay against your offers'),
    ('job_link', 'Job link', 'reopen the posting and re-import details later'),
    ('job_description', 'Job description', 'match your resume against the posting'),
)


def _rate(part, whole):
    return f'{(part / whole * 100):.1f}' if whole else '0.0'


def _application_round(status, current_round):
    """Interview round reached, from a ROUND_n status or the stored round."""
    if status and status.startswith('ROUND_'):
        suffix = status[len('ROUND_') :]
        if suffix.isdigit():
            return int(suffix)
    return current_round or 0


def _group_location(office_location, location):
    """City-level label, matching how the dashboard has always grouped locations."""
    raw = (office_location or location or '').strip()
    if not raw:
        raw = 'Unknown'
    label = raw.split(',')[0].strip()
    if 'remote' in label.lower():
        return 'Remote'
    return label[:1].upper() + label[1:]


def _as_date(value):
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    if isinstance(value, date):
        return value
    return None


def build_application_stats(user, year=None):
    from ..models import Application

    all_applications = Application.objects.filter(user=user)
    queryset = all_applications
    if year:
        queryset = queryset.filter(date_applied__year=year)

    # Read from the unfiltered set so picking a year does not remove every other option.
    years = sorted(
        {
            applied.year
            for applied in all_applications.exclude(date_applied=None)
            .values_list('date_applied', flat=True)
            .distinct()
        },
        reverse=True,
    )

    total_for_fields = queryset.count()
    blank_counts = (
        queryset.aggregate(
            **{
                name: Count('pk', filter=Q(**{name: ''}) | Q(**{f'{name}__isnull': True}))
                for name, _, _ in COMPLETENESS_FIELDS
            }
        )
        if total_for_fields
        else {}
    )
    field_completeness = [
        {
            'field': name,
            'label': label,
            'missing': blank_counts.get(name, 0),
            'total': total_for_fields,
            'unlocks': unlocks,
        }
        for name, label, unlocks in COMPLETENESS_FIELDS
        if blank_counts.get(name, 0)
    ]
    field_completeness.sort(key=lambda row: -row['missing'])

    rows = queryset.values_list(
        'status', 'current_round', 'date_applied', 'created_at', 'office_location', 'location'
    )

    today = timezone.localdate()
    total = 0
    offers = 0
    ghosted = 0
    active_interviews = 0
    total_interviews = 0
    responded = 0
    recent_30d = 0
    location_counts = defaultdict(int)
    age_counts = dict.fromkeys(AGE_BUCKETS, 0)
    daily = defaultdict(int)

    for status, current_round, date_applied, created_at, office_location, location in rows:
        total += 1
        if status in OFFER_STATUSES:
            offers += 1
        if status == 'GHOSTED':
            ghosted += 1
        if status not in INACTIVE_STATUSES:
            active_interviews += 1
        if status not in RESPONDED_EXCLUDE_STATUSES:
            responded += 1
        # A rejection counts as interviewed only if a round was actually reached.
        if (status not in RESPONDED_EXCLUDE_STATUSES and status != 'REJECTED') or (
            status == 'REJECTED' and _application_round(status, current_round) > 0
        ):
            total_interviews += 1

        location_counts[_group_location(office_location, location)] += 1

        if date_applied:
            daily[date_applied.isoformat()] += 1

        effective = _as_date(date_applied) or _as_date(created_at)
        if effective is None:
            age_counts['Undated'] += 1
        else:
            age_days = max(0, (today - effective).days)
            if age_days <= 7:
                age_counts['Last 7 days'] += 1
            elif age_days <= 30:
                age_counts['8-30 days'] += 1
            elif age_days <= 90:
                age_counts['31-90 days'] += 1
            else:
                age_counts['90+ days'] += 1
            # Matches the browser's old wall-clock comparison, to hold the number steady.
            if age_days < 30:
                recent_30d += 1

    return {
        'total': total,
        'offers': offers,
        'ghosted': ghosted,
        'active_interviews': active_interviews,
        'total_interviews': total_interviews,
        'responded_count': responded,
        'response_rate': _rate(responded, total),
        'offer_rate': _rate(offers, total),
        'recent_applications_30d': recent_30d,
        'locations': [
            {'name': name, 'count': count}
            for name, count in sorted(location_counts.items(), key=lambda item: -item[1])
        ],
        'application_age_breakdown': [
            {'name': name, 'count': age_counts[name]} for name in AGE_BUCKETS if age_counts[name]
        ],
        # {'2026-08-12': 5, ...}
        'daily_applied': dict(sorted(daily.items())),
        'years': years,
        'field_completeness': field_completeness,
    }
