from datetime import datetime

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..conflict_detector import check_for_conflicts
from ..models import Event
from ..recurrence import delete_recurring_series, generate_recurring_instances, update_recurring_series
from ..serializers import EventSerializer
from ..utils import export_data


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This event is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        data = serializer.validated_data
        conflicts = check_for_conflicts(data)
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

    def perform_update(self, serializer):
        data = serializer.validated_data
        instance = serializer.instance
        full_data = {
            'date': data.get('date', instance.date),
            'start_time': data.get('start_time', instance.start_time),
            'end_time': data.get('end_time', instance.end_time),
        }

        conflicts = check_for_conflicts(full_data, exclude_id=instance.id)
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

    def get_queryset(self):
        queryset = Event.objects.all()
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

    @action(detail=False, methods=['get'])
    def recurring_instances(self, request):
        start_str = request.query_params.get('start_date')
        end_str = request.query_params.get('end_date')
        if not start_str or not end_str:
            return Response({'error': 'start_date and end_date are required'}, status=status.HTTP_400_BAD_REQUEST)

        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

        recurring_events = Event.objects.filter(is_recurring=True, parent_event__isnull=True)
        all_instances = []
        for event in recurring_events:
            all_instances.extend(generate_recurring_instances(event, start_date, end_date))
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
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=['put'])
    def update_series(self, request, pk=None):
        event = self.get_object()
        if not event.is_recurring:
            return Response({'error': 'This is not a recurring event'}, status=status.HTTP_400_BAD_REQUEST)

        count = update_recurring_series(event, request.data)
        return Response({'message': f'Updated {count} events in the series'})

    @action(detail=True, methods=['delete'])
    def delete_series(self, request, pk=None):
        event = self.get_object()
        if not event.is_recurring:
            return Response({'error': 'This is not a recurring event'}, status=status.HTTP_400_BAD_REQUEST)

        count = delete_recurring_series(event)
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

        return Response({'message': f'Deleted instance on {date_str}'})

    @action(detail=False, methods=['post'])
    def detect_conflicts(self, request):
        from ..conflict_detector import detect_all_conflicts

        count = detect_all_conflicts()
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
        events = get_upcoming_events(days)
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), self.get_serializer_class(), fmt, 'events')

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        count, _ = Event.objects.filter(is_locked=False).delete()
        return Response(
            {'message': f'Deleted {count} events. Locked events were preserved.'},
            status=status.HTTP_200_OK,
        )
