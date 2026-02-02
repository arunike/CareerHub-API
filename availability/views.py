from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.http import HttpResponse
from .models import Event, CustomHoliday, AvailabilityOverride, AvailabilitySetting, EventCategory, UserSettings, ConflictAlert
from .serializers import (
    EventSerializer, CustomHolidaySerializer, AvailabilityOverrideSerializer, 
    AvailabilitySettingSerializer, EventCategorySerializer, UserSettingsSerializer, ConflictAlertSerializer
)
from .utils import get_next_two_weeks_weekdays, calculate_availability_for_dates, get_federal_holidays, export_data
from .recurrence import generate_recurring_instances, update_recurring_series, delete_recurring_series
from .conflict_detector import check_for_conflicts
from datetime import datetime, timedelta
import zipfile
import io
import json
import pandas as pd
from career.models import Application, Company, Offer
from career.serializers import ApplicationSerializer, CompanySerializer, ApplicationExportSerializer, OfferSerializer

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {"error": "This event is locked and cannot be deleted. Unlock it first."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        data = serializer.validated_data
        
        # Check for conflicts
        conflicts = check_for_conflicts(data)
        if conflicts:
             # Check if user wants to force despite conflicts
             force = self.request.query_params.get('force', 'false').lower() == 'true'
             if not force:
                 conflict_names = ", ".join([e.name for e in conflicts])
                 raise ValidationError({
                     "conflict": True,
                     "message": f"This event conflicts with: {conflict_names}",
                     "conflicting_events": [e.id for e in conflicts]
                 })
                 
        serializer.save()

    def perform_update(self, serializer):
        data = serializer.validated_data
        instance = serializer.instance
        
        # Check for conflicts (excluding self)
        # Update data with instance data for fields not present in update
        full_data = {
            'date': data.get('date', instance.date),
            'start_time': data.get('start_time', instance.start_time),
            'end_time': data.get('end_time', instance.end_time)
        }
        
        conflicts = check_for_conflicts(full_data, exclude_id=instance.id)
        if conflicts:
             # Check if user wants to force despite conflicts
             force = self.request.query_params.get('force', 'false').lower() == 'true'
             if not force:
                 conflict_names = ", ".join([e.name for e in conflicts])
                 raise ValidationError({
                     "conflict": True,
                     "message": f"This event conflicts with: {conflict_names}",
                     "conflicting_events": [e.id for e in conflicts]
                 })
                 
        serializer.save()

    def get_queryset(self):
        queryset = Event.objects.all()
        start = self.request.query_params.get('start_date')
        end = self.request.query_params.get('end_date')
        include_instances = self.request.query_params.get('include_instances', 'true').lower() == 'true'
        
        with open('debug_queryset.log', 'a') as f:
            f.write(f"DEBUG {datetime.now()}: All events count: {queryset.count()}\n")
            f.write(f"DEBUG: Params - start: {start}, end: {end}, include_instances: {include_instances}\n")

        if start:
            # ...
            pass
        if end:
            # ...
            pass
            
        # ... 

        if start:
            queryset = queryset.filter(date__gte=start)
        if end:
            queryset = queryset.filter(date__lte=end)
        
        # Optionally exclude recurring event instances (only show parent events)
        if not include_instances:
            queryset = queryset.filter(parent_event__isnull=True)
            
        with open('debug_queryset.log', 'a') as f:
            f.write(f"DEBUG: Final count: {queryset.count()}\n")

        return queryset
    
    @action(detail=False, methods=['get'])
    def recurring_instances(self, request):
        """Generate instances for all recurring events within a date range"""
        start_str = request.query_params.get('start_date')
        end_str = request.query_params.get('end_date')
        
        if not start_str or not end_str:
            return Response(
                {"error": "start_date and end_date are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
        
        # Get all recurring parent events
        recurring_events = Event.objects.filter(is_recurring=True, parent_event__isnull=True)
        
        all_instances = []
        for event in recurring_events:
            instances = generate_recurring_instances(event, start_date, end_date)
            all_instances.extend(instances)
        
        return Response(all_instances)
    
    @action(detail=True, methods=['post'])
    def set_recurrence(self, request, pk=None):
        event = self.get_object()
        recurrence_rule = request.data.get('recurrence_rule')
        
        if not recurrence_rule:
            return Response(
                {"error": "recurrence_rule is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        event.is_recurring = True
        event.recurrence_rule = recurrence_rule
        event.save()
        
        serializer = self.get_serializer(event)
        return Response(serializer.data)
    
    @action(detail=True, methods=['put'])
    def update_series(self, request, pk=None):
        event = self.get_object()
        
        if not event.is_recurring:
            return Response(
                {"error": "This is not a recurring event"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        updates = request.data
        count = update_recurring_series(event, updates)
        
        return Response({"message": f"Updated {count} events in the series"})
    
    @action(detail=True, methods=['delete'])
    def delete_series(self, request, pk=None):
        """Delete all instances in a recurring series"""
        event = self.get_object()
        
        if not event.is_recurring:
            return Response(
                {"error": "This is not a recurring event"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        count = delete_recurring_series(event)
        
        return Response({"message": f"Deleted {count} events in the series"})

    @action(detail=True, methods=['post'])
    def delete_instance(self, request, pk=None):
        event = self.get_object()
        date_str = request.data.get('date')
        
        if not event.is_recurring:
             return Response(
                {"error": "This is not a recurring event"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if not date_str:
            return Response(
                {"error": "date is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Initialize recurrence rule if needed (should exist if is_recurring is True)
        if not event.recurrence_rule:
             return Response(
                {"error": "Recurrence rule is missing"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Add date to excluded_dates
        if 'excluded_dates' not in event.recurrence_rule:
            event.recurrence_rule['excluded_dates'] = []
            
        if date_str not in event.recurrence_rule['excluded_dates']:
            event.recurrence_rule['excluded_dates'].append(date_str)
            event.save()
            
        return Response({"message": f"Deleted instance on {date_str}"})
    
    @action(detail=False, methods=['post'])
    def detect_conflicts(self, request):
        from .conflict_detector import detect_all_conflicts
        count = detect_all_conflicts()
        return Response({"message": f"Detected {count} conflicts", "count": count})
    
    @action(detail=True, methods=['get'])
    def check_conflicts(self, request, pk=None):
        from .conflict_detector import detect_conflicts_for_event
        event = self.get_object()
        conflicts = detect_conflicts_for_event(event)
        serializer = self.get_serializer(conflicts, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        from .conflict_detector import get_upcoming_events
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
        # Only delete unlocked events
        count, _ = Event.objects.filter(is_locked=False).delete()
        return Response(
            {"message": f"Deleted {count} events. Locked events were preserved."},
            status=status.HTTP_200_OK
        )

class HolidayViewSet(viewsets.ModelViewSet):
    queryset = CustomHoliday.objects.all()
    serializer_class = CustomHolidaySerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {"error": "This holiday is locked and cannot be deleted. Unlock it first."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def federal(self, request):
        year = datetime.now().year
        holidays_dict = get_federal_holidays(year)
        data = [
            {"date": d.strftime("%Y-%m-%d"), "description": name}
            for d, name in sorted(holidays_dict.items())
        ]
        return Response(data)

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), self.get_serializer_class(), fmt, 'holidays')

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        # Only delete unlocked holidays
        count, _ = CustomHoliday.objects.filter(is_locked=False).delete()
        return Response(
            {"message": f"Deleted {count} holidays. Locked holidays were preserved."},
            status=status.HTTP_200_OK
        )

class AvailabilityOverrideViewSet(viewsets.ModelViewSet):
    queryset = AvailabilityOverride.objects.all()
    serializer_class = AvailabilityOverrideSerializer

class AvailabilitySettingViewSet(viewsets.ModelViewSet):
    queryset = AvailabilitySetting.objects.all()
    serializer_class = AvailabilitySettingSerializer
    lookup_field = 'key'

class AvailabilityViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['get'])
    def generate(self, request):
        target_tz = request.query_params.get('timezone', 'PT')
        start_date_str = request.query_params.get('start_date', None)
        
        start_date = None
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            except ValueError:
                return Response({"error": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Calculate dates
        dates = get_next_two_weeks_weekdays(start_date)
        
        # 2. Calculate availability text
        availability_map = calculate_availability_for_dates(dates, target_tz)
        
        # 3. Format for frontend
        response_data = []
        for date_obj in dates:
            date_str = date_obj.strftime("%Y-%m-%d")
            availability = availability_map.get(date_str)
            
            if availability:
                response_data.append(availability)
        
        return Response(response_data)

class ImportViewSet(viewsets.ViewSet):
    def create(self, request):
        from .utils import parse_import_file
        
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=400)
            
        filename = file_obj.name.lower()
        file_type = 'json' if filename.endswith('.json') else 'ics' if filename.endswith('.ics') else None
        
        if not file_type:
             return Response({"error": "Unsupported file type. Use .json or .ics"}, status=400)
             
        items = parse_import_file(file_obj, file_type)
        
        created_count = 0
        
        for item in items:
            try:
                if item['classification'] == 'holiday':
                    CustomHoliday.objects.create(
                        date=item['date'],
                        description=item['summary'],
                        is_recurring=True
                    )
                else:
                    Event.objects.create(
                        name=item['summary'],
                        date=item['date'],
                        start_time=item['start_time'],
                        end_time=item['end_time'],
                        timezone='PT'
                    )
                created_count += 1
            except Exception as e:
                print(f"Skipping item {item}: {e}")
                
        return Response({"message": f"Successfully imported {created_count} items"})

class EventCategoryViewSet(viewsets.ModelViewSet):
    queryset = EventCategory.objects.all()
    serializer_class = EventCategorySerializer

class UserSettingsViewSet(viewsets.ModelViewSet):
    queryset = UserSettings.objects.all()
    serializer_class = UserSettingsSerializer
    
    @action(detail=False, methods=['get', 'put'])
    def current(self, request):
        settings, created = UserSettings.objects.get_or_create(id=1)
        
        if request.method == 'GET':
            serializer = self.get_serializer(settings)
            return Response(serializer.data)
        elif request.method == 'PUT':
            serializer = self.get_serializer(settings, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def export_all(self, request):
        fmt = request.query_params.get('fmt', 'json')
        
        # Gather Data QuerySets/Lists
        events = Event.objects.all()
        holidays = CustomHoliday.objects.all()
        apps = Application.objects.all()
        settings = UserSettings.objects.all()
        categories = EventCategory.objects.all()
        
        data_map = {
            'events': (events, EventSerializer),
            'holidays': (holidays, CustomHolidaySerializer),
            'applications': (apps, ApplicationExportSerializer),
            'user_settings': (settings, UserSettingsSerializer),
            'categories': (categories, EventCategorySerializer),
        }

        # Excel Export (Single File, Multiple Sheets)
        if fmt == 'xlsx' or fmt == 'excel':
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                for name, (qs, ser_cls) in data_map.items():
                    data = ser_cls(qs, many=True).data
                    df = pd.DataFrame(data) if data else pd.DataFrame()
                    # Sheet name limit 31 chars
                    sheet_name = name[:31] 
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            response = HttpResponse(buffer.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename="availability_manager_export_{datetime.now().strftime("%Y%m%d")}.xlsx"'
            return response

        # ZIP Export (CSV or JSON)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for name, (qs, ser_cls) in data_map.items():
                data = ser_cls(qs, many=True).data
                
                if fmt == 'csv':
                    df = pd.DataFrame(data) if data else pd.DataFrame()
                    csv_buffer = io.StringIO()
                    df.to_csv(csv_buffer, index=False)
                    zip_file.writestr(f"{name}.csv", csv_buffer.getvalue())
                else:
                    # Default JSON
                    json_str = json.dumps(data, indent=2, default=str)
                    zip_file.writestr(f"{name}.json", json_str)
            
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        response = HttpResponse(buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="availability_manager_backup_{timestamp}.zip"'
        return response

class ConflictAlertViewSet(viewsets.ModelViewSet):
    queryset = ConflictAlert.objects.all()
    serializer_class = ConflictAlertSerializer
    
    @action(detail=False, methods=['get'])
    def unresolved(self, request):
        conflicts = ConflictAlert.objects.filter(resolved=False)
        serializer = self.get_serializer(conflicts, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        conflict = self.get_object()
        conflict.resolved = True
        conflict.save()
        return Response({"message": "Conflict resolved"})
