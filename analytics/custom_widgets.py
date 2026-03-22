import hashlib
import json
import logging
import os
import urllib.request

from django.core.cache import cache
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from datetime import datetime, timedelta
import re

from availability.models import Event
from career.models import Application, Offer

logger = logging.getLogger(__name__)


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


def _build_db_summary() -> dict:
    """Gather aggregated DB stats to give the LLM enough context to answer analytics queries."""
    app_by_status = list(
        Application.objects.values('status').annotate(count=Count('id')).order_by('status')
    )
    event_by_category = list(
        Event.objects.values('category__name').annotate(count=Count('id')).order_by('-count')
    )
    return {
        'applications': {
            'total': Application.objects.count(),
            'by_status': [{'status': r['status'], 'count': r['count']} for r in app_by_status],
            'offers_count': Application.objects.filter(status__in=['OFFER', 'ACCEPTED']).count(),
            'active_count': Application.objects.exclude(
                status__in=['REJECTED', 'GHOSTED', 'ACCEPTED']
            ).count(),
        },
        'events': {
            'total': Event.objects.count(),
            'by_category': [
                {'category': r['category__name'] or 'Uncategorized', 'count': r['count']}
                for r in event_by_category
            ],
        },
    }


def _llm_fallback(query_text: str, context: str) -> dict:
    """Use the LLM to answer queries that the regex engine couldn't handle."""
    llm_url = os.environ.get('LLM_API_URL', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions')
    llm_key = os.environ.get('LLM_API_KEY', '')
    llm_model = os.environ.get('LLM_MODEL', 'gemini-2.0-flash')

    if not llm_url or not llm_key:
        return {'error': 'Query not understood', 'suggestion': 'Try "Total events" or "Applications by status"'}

    db_summary = _build_db_summary()

    prompt = f"""You are an analytics assistant for a job search tracker app.
Answer the following query using ONLY the database summary provided. Do not make up data.
Query context: {context} (either 'job-hunt' for application/offer data, or 'availability' for events/calendar data).

DATABASE SUMMARY:
{json.dumps(db_summary, indent=2)}

QUERY: {query_text}

Respond ONLY with a valid JSON object in exactly one of these two formats:
Single metric: {{"type": "metric", "value": <number>, "unit": "<short label>"}}
Chart data:    {{"type": "chart", "data": [{{"name": "<label>", "value": <number>}}], "chartType": "bar" or "pie"}}

If you cannot answer from the data provided, respond with:
{{"error": "Cannot answer this query from available data"}}"""

    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {llm_key}'}
    payload = json.dumps({
        'model': llm_model,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.1,
    }).encode('utf-8')

    try:
        req = urllib.request.Request(llm_url, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode('utf-8'))
            content = result['choices'][0]['message']['content'].strip()
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()
            return json.loads(content)
    except Exception as exc:
        logger.error('LLM analytics fallback failed: %s', exc)
        return {'error': 'Query not understood', 'suggestion': 'Try "Total events" or "Applications by status"'}


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

    return _llm_fallback(query_text, context)


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
