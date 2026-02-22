from datetime import datetime, timedelta
from uuid import uuid4

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Event, PublicBooking, ShareLink
from ..serializers import PublicBookingSerializer, ShareLinkSerializer
from ..utils import calculate_availability_for_dates


def _parse_slot_ranges(availability_text):
    slots = []
    if not availability_text:
        return slots

    parts = [part.strip() for part in str(availability_text).split(',') if part.strip()]
    for part in parts:
        if ' - ' not in part:
            continue
        start_str, end_str = [item.strip() for item in part.split(' - ', 1)]
        try:
            start_dt = datetime.strptime(start_str, '%I:%M %p')
            end_dt = datetime.strptime(end_str, '%I:%M %p')
        except ValueError:
            continue
        slots.append(
            {
                'start_time': start_dt.strftime('%H:%M:%S'),
                'end_time': end_dt.strftime('%H:%M:%S'),
                'label': f'{start_str} - {end_str}',
            }
        )
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
    bookings = PublicBooking.objects.filter(share_link=link, date=date_obj).values_list('start_time', 'end_time')
    blocked_slots = set(bookings)
    return [slot for slot in slots if (slot['start_time'], slot['end_time']) not in blocked_slots]


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
        return Response({'active': self.get_serializer(link).data})

    @action(detail=False, methods=['post'])
    def generate(self, request):
        title = request.data.get('title') or 'My Availability'
        duration_days_raw = request.data.get('duration_days', 7)
        try:
            duration_days = max(1, min(90, int(duration_days_raw)))
        except (TypeError, ValueError):
            duration_days = 7

        ShareLink.objects.filter(is_active=True).update(is_active=False)
        link = ShareLink.objects.create(
            uuid=str(uuid4()),
            title=title,
            duration_days=duration_days,
            expires_at=timezone.now() + timedelta(days=duration_days),
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

        rows = []
        for date_obj in dates:
            date_key = date_obj.strftime('%Y-%m-%d')
            availability_item = availability_map.get(date_key)
            raw_text = availability_item['availability'] if availability_item else None
            slots = _filter_booked_slots(link, date_obj, _parse_slot_ranges(raw_text))
            rows.append(
                {
                    'date': date_key,
                    'day_name': date_obj.strftime('%A'),
                    'readable_date': date_obj.strftime('%b %d'),
                    'slots': slots,
                }
            )

        return Response(
            {
                'title': link.title,
                'expires_at': link.expires_at,
                'timezone': timezone_code,
                'days': rows,
            }
        )


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
        slots = _filter_booked_slots(
            link,
            booking_date,
            _parse_slot_ranges(availability_item['availability'] if availability_item else None),
        )
        matched_slot = any(slot['start_time'] == start_time and slot['end_time'] == end_time for slot in slots)
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
            name=f'Booking - {name}',
            date=booking_date,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone_code,
            location_type='virtual',
            notes=f'Public booking via share link ({email})\n{notes}'.strip(),
            is_locked=True,
        )

        return Response(
            {
                'message': 'Booking confirmed.',
                'booking': PublicBookingSerializer(booking).data,
            },
            status=status.HTTP_201_CREATED,
        )
