from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.http import HttpResponse
from django.utils import timezone
from .models import Event, CustomHoliday, AvailabilityOverride, AvailabilitySetting, EventCategory, UserSettings, ConflictAlert, ShareLink, PublicBooking
from .serializers import (
    EventSerializer, CustomHolidaySerializer, AvailabilityOverrideSerializer, 
    AvailabilitySettingSerializer, EventCategorySerializer, UserSettingsSerializer, ConflictAlertSerializer,
    ShareLinkSerializer, PublicBookingSerializer
)
from .utils import get_next_two_weeks_weekdays, calculate_availability_for_dates, get_federal_holidays, export_data
from .recurrence import generate_recurring_instances, update_recurring_series, delete_recurring_series
from .conflict_detector import check_for_conflicts
from datetime import datetime, timedelta
from uuid import uuid4
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


def _parse_slot_ranges(availability_text):
    slots = []
    if not availability_text:
        return slots
    parts = [p.strip() for p in str(availability_text).split(',') if p.strip()]
    for part in parts:
        if ' - ' not in part:
            continue
        start_str, end_str = [x.strip() for x in part.split(' - ', 1)]
        try:
            start_dt = datetime.strptime(start_str, '%I:%M %p')
            end_dt = datetime.strptime(end_str, '%I:%M %p')
        except ValueError:
            continue
        slots.append({
            'start_time': start_dt.strftime('%H:%M:%S'),
            'end_time': end_dt.strftime('%H:%M:%S'),
            'label': f"{start_str} - {end_str}",
        })
    return slots


def _get_share_link_or_none(uuid_value):
    link = ShareLink.objects.filter(uuid=uuid_value, is_active=True).first()
    if not link:
        return None
    if link.expires_at <= timezone.now():
        link.is_active = False
        link.save(update_fields=['is_active'])
        return None
    return link


def _filter_booked_slots(link, date_obj, slots):
    bookings = PublicBooking.objects.filter(share_link=link, date=date_obj).values_list(
        'start_time',
        'end_time',
    )
    blocked = set(bookings)
    return [s for s in slots if (s['start_time'], s['end_time']) not in blocked]


class ShareLinkViewSet(viewsets.ModelViewSet):
    queryset = ShareLink.objects.all().order_by('-created_at')
    serializer_class = ShareLinkSerializer

    @action(detail=False, methods=['get'])
    def current(self, request):
        now = timezone.now()
        ShareLink.objects.filter(is_active=True, expires_at__lte=now).update(is_active=False)
        link = ShareLink.objects.filter(is_active=True, expires_at__gt=now).order_by('-created_at').first()
        if not link:
            return Response({'active': None})
        data = self.get_serializer(link).data
        return Response({'active': data})

    @action(detail=False, methods=['post'])
    def generate(self, request):
        title = request.data.get('title') or 'My Availability'
        duration_days_raw = request.data.get('duration_days', 7)
        try:
            duration_days = max(1, min(90, int(duration_days_raw)))
        except (TypeError, ValueError):
            duration_days = 7

        ShareLink.objects.filter(is_active=True).update(is_active=False)
        expires_at = timezone.now() + timedelta(days=duration_days)
        link = ShareLink.objects.create(
            uuid=str(uuid4()),
            title=title,
            duration_days=duration_days,
            expires_at=expires_at,
            is_active=True,
        )
        return Response(self.get_serializer(link).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def deactivate(self, request):
        now = timezone.now()
        count = ShareLink.objects.filter(is_active=True, expires_at__gt=now).update(is_active=False)
        return Response({'message': f'Deactivated {count} active link(s).'})


class PublicBookingSlotsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, uuid):
        link = _get_share_link_or_none(uuid)
        if not link:
            return Response({'error': 'This booking link is invalid or expired.'}, status=404)

        timezone_code = request.query_params.get('timezone', 'PT')
        date_str = request.query_params.get('date')
        days_raw = request.query_params.get('days', 14)
        try:
            days = max(1, min(30, int(days_raw)))
        except (TypeError, ValueError):
            days = 14

        start_date = timezone.now().date()
        if date_str:
            try:
                start_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

        dates = [start_date + timedelta(days=i) for i in range(days)]
        availability_map = calculate_availability_for_dates(dates, timezone_code)

        items = []
        for d in dates:
            date_key = d.strftime('%Y-%m-%d')
            availability_item = availability_map.get(date_key)
            raw_text = availability_item['availability'] if availability_item else None
            slots = _parse_slot_ranges(raw_text)
            slots = _filter_booked_slots(link, d, slots)
            items.append({
                'date': date_key,
                'day_name': d.strftime('%A'),
                'readable_date': d.strftime('%b %d'),
                'slots': slots,
            })

        return Response({
            'title': link.title,
            'expires_at': link.expires_at,
            'timezone': timezone_code,
            'days': items,
        })


class PublicBookingCreateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, uuid):
        link = _get_share_link_or_none(uuid)
        if not link:
            return Response({'error': 'This booking link is invalid or expired.'}, status=404)

        name = (request.data.get('name') or '').strip()
        email = (request.data.get('email') or '').strip()
        date_str = request.data.get('date')
        start_time = request.data.get('start_time')
        end_time = request.data.get('end_time')
        notes = (request.data.get('notes') or '').strip()
        timezone_code = request.data.get('timezone') or 'PT'

        if not name or not email or not date_str or not start_time or not end_time:
            return Response({'error': 'name, email, date, start_time, and end_time are required.'}, status=400)

        try:
            booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

        availability_map = calculate_availability_for_dates([booking_date], timezone_code)
        availability_item = availability_map.get(date_str)
        slots = _parse_slot_ranges(availability_item['availability'] if availability_item else None)
        slots = _filter_booked_slots(link, booking_date, slots)
        matched_slot = any(s['start_time'] == start_time and s['end_time'] == end_time for s in slots)
        if not matched_slot:
            return Response({'error': 'Selected slot is no longer available. Please refresh and pick another.'}, status=409)

        booking = PublicBooking.objects.create(
            share_link=link,
            name=name,
            email=email,
            date=booking_date,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone_code,
            notes=notes,
        )

        Event.objects.create(
            name=f"Booking - {name}",
            date=booking_date,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone_code,
            location_type='virtual',
            notes=f"Public booking via share link ({email})\n{notes}".strip(),
            is_locked=True,
        )

        return Response(
            {
                'message': 'Booking confirmed.',
                'booking': PublicBookingSerializer(booking).data,
            },
            status=status.HTTP_201_CREATED,
        )
