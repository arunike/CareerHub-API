from datetime import datetime, timedelta

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.core.cache import cache
from django.utils import timezone

from ..cache import get_events_cache_key, invalidate_events_cache
from ..conflict_detector import check_for_conflicts
from ..models import Event
from ..recurrence import delete_recurring_series, generate_recurring_instances, update_recurring_series
from ..serializers import EventCategorySerializer, EventSerializer
from ..utils import export_data



class ConditionalPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        if 'page' not in request.query_params:
            return None
        return super().paginate_queryset(queryset, request, view)


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    pagination_class = ConditionalPageNumberPagination

    def list(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = get_events_cache_key(user_id, "list", request.query_params)
        
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)
            
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            cache.set(cache_key, response.data, timeout=300)
            return response
            
        serializer = self.get_serializer(queryset, many=True)
        response_data = serializer.data
        cache.set(cache_key, response_data, timeout=300)
        return Response(response_data)


    def get_queryset(self):
        queryset = Event.objects.filter(user=self.request.user).select_related(
            'category',
            'application__company',
        )
        start = self.request.query_params.get('start_date')
        end = self.request.query_params.get('end_date')
        include_instances = self.request.query_params.get('include_instances', 'true').lower() == 'true'

        if start:
            queryset = queryset.filter(date__gte=start)
        if end:
            queryset = queryset.filter(date__lte=end)
        if not include_instances:
            queryset = queryset.filter(parent_event__isnull=True)
        return queryset

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This event is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        response = super().destroy(request, *args, **kwargs)
        invalidate_events_cache(request.user.id)
        return response

    def perform_create(self, serializer):
        data = serializer.validated_data
        conflicts = check_for_conflicts(data, self.request.user)
        if conflicts:
            force = self.request.query_params.get('force', 'false').lower() == 'true'
            if not force:
                conflict_names = ', '.join([e.name for e in conflicts])
                raise ValidationError(
                    {
                        'conflict': True,
                        'message': f'This event conflicts with: {conflict_names}',
                        'conflicting_events': [e.id for e in conflicts],
                    }
                )
        serializer.save(user=self.request.user)
        invalidate_events_cache(self.request.user.id)

    def perform_update(self, serializer):
        data = serializer.validated_data
        instance = serializer.instance
        full_data = {
            'date': data.get('date', instance.date),
            'start_time': data.get('start_time', instance.start_time),
            'end_time': data.get('end_time', instance.end_time),
            'timezone': data.get('timezone', instance.timezone),
        }

        conflicts = check_for_conflicts(full_data, self.request.user, exclude_id=instance.id)
        if conflicts:
            force = self.request.query_params.get('force', 'false').lower() == 'true'
            if not force:
                conflict_names = ', '.join([e.name for e in conflicts])
                raise ValidationError(
                    {
                        'conflict': True,
                        'message': f'This event conflicts with: {conflict_names}',
                        'conflicting_events': [e.id for e in conflicts],
                    }
                )
        serializer.save()
        invalidate_events_cache(self.request.user.id)

    @action(detail=False, methods=['get'])
    def feed(self, request):
        params = request.query_params
        year = (params.get('year') or '').strip()
        start = (params.get('start_date') or '').strip()
        end = (params.get('end_date') or '').strip()
        category = (params.get('category') or '').strip()
        sort_by = (params.get('sort_by') or 'date').strip()
        sort_order = (params.get('sort_order') or 'desc').strip()

        regular_events = (
            Event.objects
            .filter(user=request.user, parent_event__isnull=True, is_recurring=False)
            .select_related('category', 'application__company')
        )
        recurring_events = (
            Event.objects
            .filter(user=request.user, parent_event__isnull=True, is_recurring=True)
            .select_related('category', 'application__company')
        )

        if category and category != 'ALL':
            regular_events = regular_events.filter(category_id=category)
            recurring_events = recurring_events.filter(category_id=category)

        recurring_start = None
        recurring_end = None
        if year and year != 'all':
            try:
                year_value = int(year)
            except ValueError:
                regular_events = regular_events.none()
                recurring_events = recurring_events.none()
            else:
                regular_events = regular_events.filter(date__year=year_value)
                recurring_start = datetime(year_value, 1, 1).date()
                recurring_end = datetime(year_value, 12, 31).date()

        if start:
            regular_events = regular_events.filter(date__gte=start)
            parsed_start = datetime.strptime(start, '%Y-%m-%d').date()
            recurring_start = max(recurring_start, parsed_start) if recurring_start else parsed_start
        if end:
            regular_events = regular_events.filter(date__lte=end)
            parsed_end = datetime.strptime(end, '%Y-%m-%d').date()
            recurring_end = min(recurring_end, parsed_end) if recurring_end else parsed_end

        if recurring_start is None or recurring_end is None:
            today = timezone.now().date()
            recurring_start = today - timedelta(days=31)
            recurring_end = today + timedelta(days=366)

        serializer = self.get_serializer(regular_events, many=True)
        items = list(serializer.data)

        virtual_index = 0
        for event in recurring_events:
            for instance in generate_recurring_instances(event, recurring_start, recurring_end):
                virtual_index += 1
                instance_date = instance['date']
                items.append({
                    'id': -1 * ((event.id * 100000) + virtual_index),
                    'name': instance['name'],
                    'date': instance_date.isoformat() if hasattr(instance_date, 'isoformat') else instance_date,
                    'start_time': instance['start_time'],
                    'end_time': instance['end_time'],
                    'timezone': instance.get('timezone') or event.timezone,
                    'category': instance.get('category'),
                    'category_details': EventCategorySerializer(event.category).data if event.category else None,
                    'color': event.color,
                    'location_type': instance.get('location_type') or event.location_type,
                    'location': instance.get('location') or '',
                    'meeting_link': instance.get('meeting_link') or '',
                    'is_recurring': False,
                    'recurrence_rule': None,
                    'parent_event': event.id,
                    'application': event.application_id,
                    'application_details': EventSerializer(event, context={'request': request}).data.get('application_details'),
                    'notes': instance.get('notes') or '',
                    'reminder_minutes': event.reminder_minutes,
                    'is_locked': event.is_locked,
                    'created_at': event.created_at.isoformat() if event.created_at else None,
                    'updated_at': event.updated_at.isoformat() if event.updated_at else None,
                    'is_virtual': True,
                })

        def sort_key(item):
            if sort_by == 'duration':
                try:
                    start_dt = datetime.strptime(item['start_time'][:8], '%H:%M:%S')
                    end_dt = datetime.strptime(item['end_time'][:8], '%H:%M:%S')
                    duration = (end_dt - start_dt).total_seconds()
                except (TypeError, ValueError):
                    duration = 0
                return (duration, item.get('date') or '', item.get('start_time') or '')
            return (item.get('date') or '', item.get('start_time') or '')

        items.sort(key=sort_key, reverse=sort_order != 'asc')
        page = self.paginate_queryset(items)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(items)

    @action(detail=False, methods=['get'])
    def recurring_instances(self, request):
        user_id = request.user.id
        cache_key = get_events_cache_key(user_id, "recurring_instances", request.query_params)
        
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)

        start_str = request.query_params.get('start_date')
        end_str = request.query_params.get('end_date')
        if not start_str or not end_str:
            return Response({'error': 'start_date and end_date are required'}, status=status.HTTP_400_BAD_REQUEST)

        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

        recurring_events = self.get_queryset().filter(is_recurring=True, parent_event__isnull=True)
        all_instances = []
        for event in recurring_events:
            all_instances.extend(generate_recurring_instances(event, start_date, end_date))
            
        cache.set(cache_key, all_instances, timeout=300)
        return Response(all_instances)

    @action(detail=True, methods=['post'])
    def set_recurrence(self, request, pk=None):
        event = self.get_object()
        recurrence_rule = request.data.get('recurrence_rule')
        if not recurrence_rule:
            return Response({'error': 'recurrence_rule is required'}, status=status.HTTP_400_BAD_REQUEST)

        event.is_recurring = True
        event.recurrence_rule = recurrence_rule
        event.save()
        invalidate_events_cache(request.user.id)
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=['put'])
    def update_series(self, request, pk=None):
        event = self.get_object()
        if not event.is_recurring:
            return Response({'error': 'This is not a recurring event'}, status=status.HTTP_400_BAD_REQUEST)

        count = update_recurring_series(event, request.data)
        invalidate_events_cache(request.user.id)
        return Response({'message': f'Updated {count} events in the series'})

    @action(detail=True, methods=['delete'])
    def delete_series(self, request, pk=None):
        event = self.get_object()
        if not event.is_recurring:
            return Response({'error': 'This is not a recurring event'}, status=status.HTTP_400_BAD_REQUEST)

        count = delete_recurring_series(event)
        invalidate_events_cache(request.user.id)
        return Response({'message': f'Deleted {count} events in the series'})

    @action(detail=True, methods=['post'])
    def delete_instance(self, request, pk=None):
        event = self.get_object()
        date_str = request.data.get('date')

        if not event.is_recurring:
            return Response({'error': 'This is not a recurring event'}, status=status.HTTP_400_BAD_REQUEST)
        if not date_str:
            return Response({'error': 'date is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not event.recurrence_rule:
            return Response({'error': 'Recurrence rule is missing'}, status=status.HTTP_400_BAD_REQUEST)

        if 'excluded_dates' not in event.recurrence_rule:
            event.recurrence_rule['excluded_dates'] = []
        if date_str not in event.recurrence_rule['excluded_dates']:
            event.recurrence_rule['excluded_dates'].append(date_str)
            event.save()
            invalidate_events_cache(request.user.id)

        return Response({'message': f'Deleted instance on {date_str}'})

    @action(detail=False, methods=['post'])
    def detect_conflicts(self, request):
        from ..conflict_detector import detect_all_conflicts

        count = detect_all_conflicts(request.user)
        return Response({'message': f'Detected {count} conflicts', 'count': count})

    @action(detail=True, methods=['get'])
    def check_conflicts(self, request, pk=None):
        from ..conflict_detector import detect_conflicts_for_event

        event = self.get_object()
        conflicts = detect_conflicts_for_event(event)
        serializer = self.get_serializer(conflicts, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        from ..conflict_detector import get_upcoming_events

        days = int(request.query_params.get('days', 7))
        events = get_upcoming_events(days, request.user)
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), self.get_serializer_class(), fmt, 'events')

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        count, _ = self.get_queryset().filter(is_locked=False).delete()
        invalidate_events_cache(request.user.id)
        return Response(
            {'message': f'Deleted {count} events. Locked events were preserved.'},
            status=status.HTTP_200_OK,
        )
