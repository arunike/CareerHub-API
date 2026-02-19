import re
from django.db.models import Avg, Sum, Count
from datetime import datetime, timedelta
from django.utils import timezone
from availability.models import Event
from career.models import Application, Offer

def get_date_range_from_query(query):
    # Simplistic date range parsing
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
    
    # Year matching (e.g., "in 2024")
    year_match = re.search(r'in (\d{4})', query.lower())
    if year_match:
        year = int(year_match.group(1))
        # Use current timezone
        start = datetime(year, 1, 1, 0, 0, 0, 0, tzinfo=timezone.get_current_timezone())
        end = datetime(year + 1, 1, 1, 0, 0, 0, 0, tzinfo=timezone.get_current_timezone())
        return (start, end)

    return (None, None)

def process_query(query_text, context):
    query_lower = query_text.lower()
    
    # Common date filter
    start_date, end_date = get_date_range_from_query(query_lower)
    
    # Smart context switching
    # If query mentions "applications", "apps", "offer", "interview" -> force job-hunt
    if re.search(r'(application|app|offer|interview)', query_lower):
        context = 'job-hunt'
    # If query mentions "event", "meeting" -> force availability
    elif re.search(r'(event|meeting)', query_lower):
        context = 'availability'
    
    if context == 'availability':
        # Total Events
        if re.search(r'total (events|meetings)', query_lower):
            queryset = Event.objects.all()
            if start_date:
                queryset = queryset.filter(date__gte=start_date.date())
            if end_date:
                queryset = queryset.filter(date__lt=end_date.date())
            return {
                'type': 'metric',
                'value': queryset.count(),
                'unit': 'events'
            }
            
        # Average Duration
        if re.search(r'average (duration|length)', query_lower):
            return {
                'type': 'metric',
                'value': 0, 
                'unit': 'minutes (not supported yet)'
            }
            
        # Events by Category (Chart)
        if re.search(r'(events|meetings) by category', query_lower):
            queryset = Event.objects.all()
            if start_date:
                queryset = queryset.filter(date__gte=start_date.date())
            if end_date:
                queryset = queryset.filter(date__lt=end_date.date())
            
            # Group by category name
            data = queryset.values('category__name').annotate(count=Count('id')).order_by('-count')
            
            formatted_data = []
            for item in data:
                name = item['category__name'] or 'Uncategorized'
                formatted_data.append({'name': name, 'value': item['count']})
                
            return {
                'type': 'chart',
                'data': formatted_data,
                'chartType': 'pie'
            }

    elif context == 'job-hunt':
        # Total Applications
        if re.search(r'total (applications|apps)', query_lower):
            queryset = Application.objects.all()
            if start_date:
                queryset = queryset.filter(date_applied__gte=start_date)
            if end_date:
                queryset = queryset.filter(date_applied__lt=end_date)
            return {
                'type': 'metric',
                'value': queryset.count(),
                'unit': 'applications'
            }
            
        # Total Offers
        if re.search(r'total (offers|offer)', query_lower):
            queryset = Application.objects.filter(status__in=['OFFER', 'ACCEPTED'])
            if start_date:
                queryset = queryset.filter(date_applied__gte=start_date)
            if end_date:
                queryset = queryset.filter(date_applied__lt=end_date)
            return {
                'type': 'metric',
                'value': queryset.count(),
                'unit': 'offers'
            }
            
        # Active Applications
        if re.search(r'active (applications|apps)', query_lower):
            queryset = Application.objects.exclude(status__in=['REJECTED', 'GHOSTED', 'ACCEPTED']) 
            if start_date:
                queryset = queryset.filter(date_applied__gte=start_date)
            if end_date:
                queryset = queryset.filter(date_applied__lt=end_date)
            return {
                'type': 'metric',
                'value': queryset.count(),
                'unit': 'active apps'
            }

        # Apps by Status (Chart)
        if re.search(r'(applications|apps) by status', query_lower):
            queryset = Application.objects.all()
            if start_date:
                queryset = queryset.filter(date_applied__gte=start_date)
            if end_date:
                queryset = queryset.filter(date_applied__lt=end_date)
            data = queryset.values('status').annotate(count=Count('id')).order_by('-count')
            
            formatted_data = []
            for item in data:
                formatted_data.append({'name': item['status'], 'value': item['count']})

            return {
                'type': 'chart',
                'data': formatted_data,
                'chartType': 'bar'
            }

    return {'error': 'Query not understood', 'suggestion': 'Try "Total events" or "Applications by status"'}
