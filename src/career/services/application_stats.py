"""Dashboard aggregates for the applications list.

The Analytics page used to download every application in full — 963 KB for 808 rows,
mostly job descriptions and notes it never read — purely to count statuses and group
locations in the browser. These are the same counts, computed from six small columns.

The bucket definitions deliberately mirror what the frontend used to do, so moving the
work here does not change a single number on the dashboard.
"""

from collections import defaultdict
from datetime import date, datetime

from django.utils import timezone

INACTIVE_STATUSES = {'APPLIED', 'REJECTED', 'GHOSTED', 'ACCEPTED', 'REMOVED_FROM_SHEET'}
RESPONDED_EXCLUDE_STATUSES = {'APPLIED', 'GHOSTED', 'REMOVED_FROM_SHEET'}
# An offer counts once it has been made, whatever was done with it: accepting one moves the
# status to ACCEPTED, which would otherwise drop the offer rate to zero.
OFFER_STATUSES = {'OFFER', 'ACCEPTED', 'OFFER_REJECTED'}

AGE_BUCKETS = ('Last 7 days', '8-30 days', '31-90 days', '90+ days', 'Undated')


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

    # The year picker has to list every year that has applications, so it is deliberately
    # read from the unfiltered set — otherwise selecting a year would leave it as the only
    # option and there would be no way back.
    years = sorted(
        {
            applied.year
            for applied in all_applications.exclude(date_applied=None)
            .values_list('date_applied', flat=True)
            .distinct()
        },
        reverse=True,
    )

    # One query, six short columns. Everything below is arithmetic over that.
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
    # Date histogram for the activity chart: one entry per day that has applications, so the
    # chart can bucket by day, week or month without the rows themselves.
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
        # A rejection only counts as having interviewed if a round was actually reached;
        # anything else past the applied/ghosted/removed set did by definition.
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
            # The browser compared against a wall-clock instant, so a date a full 30 days
            # old already fell outside the window. Kept the same to hold the number steady.
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
        # {'2026-08-12': 5, ...} — a few hundred entries at most, versus the whole list.
        'daily_applied': dict(sorted(daily.items())),
        'years': years,
    }
