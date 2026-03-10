import hashlib

from django.core.cache import cache
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from datetime import datetime, timedelta
import re

from availability.models import Event
from career.models import Application, Offer


CACHE_KEY_PREFIX = "widget"


def _build_cache_key(query_text: str, context: str) -> str:
    raw = f"{query_text.strip().lower()}:{context}"
    digest = hashlib.md5(raw.encode()).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{digest}"


def get_date_range_from_query(query):
    now = timezone.now()
    if 'this month' in query.lower():
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (start, None)
    if 'last 30 days' in query.lower():
        start = now - timedelta(days=30)
        return (start, None)
    if 'this week' in query.lower():
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        return (start, None)

    year_match = re.search(r'in (\d{4})', query.lower())
    if year_match:
        year = int(year_match.group(1))
        start = datetime(year, 1, 1, 0, 0, 0, 0, tzinfo=timezone.get_current_timezone())
        end = datetime(year + 1, 1, 1, 0, 0, 0, 0, tzinfo=timezone.get_current_timezone())
        return (start, end)

    return (None, None)


def _compute_result(query_text: str, context: str) -> dict:
    """Execute the raw DB query and return the result dict."""
    query_lower = query_text.lower()

    start_date, end_date = get_date_range_from_query(query_lower)

    # Smart context switching
    if re.search(r'(application|app|offer|interview)', query_lower):
        context = 'job-hunt'
    elif re.search(r'(event|meeting)', query_lower):
        context = 'availability'

    if context == 'availability':
        if re.search(r'total (events|meetings)', query_lower):
            queryset = Event.objects.all()
            if start_date:
                queryset = queryset.filter(date__gte=start_date.date())
            if end_date:
                queryset = queryset.filter(date__lt=end_date.date())
            return {'type': 'metric', 'value': queryset.count(), 'unit': 'events'}

        if re.search(r'average (duration|length)', query_lower):
            return {'type': 'metric', 'value': 0, 'unit': 'minutes (not supported yet)'}

        if re.search(r'(events|meetings) by category', query_lower):
            queryset = Event.objects.all()
            if start_date:
                queryset = queryset.filter(date__gte=start_date.date())
            if end_date:
                queryset = queryset.filter(date__lt=end_date.date())
            data = queryset.values('category__name').annotate(count=Count('id')).order_by('-count')
            formatted_data = [
                {'name': item['category__name'] or 'Uncategorized', 'value': item['count']}
                for item in data
            ]
            return {'type': 'chart', 'data': formatted_data, 'chartType': 'pie'}

    elif context == 'job-hunt':
        if re.search(r'total (applications|apps)', query_lower):
            queryset = Application.objects.all()
            if start_date:
                queryset = queryset.filter(date_applied__gte=start_date)
            if end_date:
                queryset = queryset.filter(date_applied__lt=end_date)
            return {'type': 'metric', 'value': queryset.count(), 'unit': 'applications'}

        if re.search(r'total (offers|offer)', query_lower):
            queryset = Application.objects.filter(status__in=['OFFER', 'ACCEPTED'])
            if start_date:
                queryset = queryset.filter(date_applied__gte=start_date)
            if end_date:
                queryset = queryset.filter(date_applied__lt=end_date)
            return {'type': 'metric', 'value': queryset.count(), 'unit': 'offers'}

        if re.search(r'active (applications|apps)', query_lower):
            queryset = Application.objects.exclude(status__in=['REJECTED', 'GHOSTED', 'ACCEPTED'])
            if start_date:
                queryset = queryset.filter(date_applied__gte=start_date)
            if end_date:
                queryset = queryset.filter(date_applied__lt=end_date)
            return {'type': 'metric', 'value': queryset.count(), 'unit': 'active apps'}

        if re.search(r'(applications|apps) by status', query_lower):
            queryset = Application.objects.all()
            if start_date:
                queryset = queryset.filter(date_applied__gte=start_date)
            if end_date:
                queryset = queryset.filter(date_applied__lt=end_date)
            data = queryset.values('status').annotate(count=Count('id')).order_by('-count')
            formatted_data = [{'name': item['status'], 'value': item['count']} for item in data]
            return {'type': 'chart', 'data': formatted_data, 'chartType': 'bar'}

    return {'error': 'Query not understood', 'suggestion': 'Try "Total events" or "Applications by status"'}


def process_query(query_text: str, context: str) -> dict:
    cache_key = _build_cache_key(query_text, context)

    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        cached = None

    result = _compute_result(query_text, context)

    # Only cache successful results, not error responses
    if 'error' not in result:
        try:
            cache.set(cache_key, result, timeout=settings.CACHE_TTL)
        except Exception:
            pass

    return result
