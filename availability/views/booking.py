from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Event, PublicBooking, ShareLink, UserSettings
from ..serializers import PublicBookingSerializer, ShareLinkSerializer
from ..utils import calculate_availability_for_dates

TIMEZONE_CODE_TO_NAME = {
    'PT': 'America/Los_Angeles',
    'MT': 'America/Denver',
    'CT': 'America/Chicago',
    'ET': 'America/New_York',
}


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


def _normalize_timezone_code(value):
    if not value:
        return 'PT'
    upper = str(value).strip().upper()
    if upper in TIMEZONE_CODE_TO_NAME:
        return upper
    for code, tz_name in TIMEZONE_CODE_TO_NAME.items():
        if upper == tz_name.upper():
            return code
    return 'PT'


def _base_timezone_code():
    settings = UserSettings.objects.first()
    if settings and settings.primary_timezone:
        return _normalize_timezone_code(settings.primary_timezone)
    return 'PT'


def _format_label(start_dt, end_dt):
    start_str = start_dt.strftime('%I:%M %p').lstrip('0')
    end_str = end_dt.strftime('%I:%M %p').lstrip('0')
    return f'{start_str} - {end_str}'


def _convert_slots_between_timezones(date_obj, slots, from_code, to_code):
    if from_code == to_code:
        out = []
        for slot in slots:
            start_dt = datetime.strptime(slot['start_time'], '%H:%M:%S')
            end_dt = datetime.strptime(slot['end_time'], '%H:%M:%S')
            out.append(
                {
                    'start_time': slot['start_time'],
                    'end_time': slot['end_time'],
                    'label': _format_label(start_dt, end_dt),
                }
            )
        return out

    from_tz = ZoneInfo(TIMEZONE_CODE_TO_NAME[from_code])
    to_tz = ZoneInfo(TIMEZONE_CODE_TO_NAME[to_code])
    converted = []
    for slot in slots:
        s_time = datetime.strptime(slot['start_time'], '%H:%M:%S').time()
        e_time = datetime.strptime(slot['end_time'], '%H:%M:%S').time()
        s_dt_from = datetime.combine(date_obj, s_time).replace(tzinfo=from_tz)
        e_dt_from = datetime.combine(date_obj, e_time).replace(tzinfo=from_tz)
        s_dt_to = s_dt_from.astimezone(to_tz)
        e_dt_to = e_dt_from.astimezone(to_tz)
        converted.append(
            {
                'start_time': s_dt_to.strftime('%H:%M:%S'),
                'end_time': e_dt_to.strftime('%H:%M:%S'),
                'label': _format_label(s_dt_to, e_dt_to),
            }
        )
    return converted


def _convert_slot_to_base(date_obj, start_time, end_time, from_code, to_code):
    from_tz = ZoneInfo(TIMEZONE_CODE_TO_NAME[from_code])
    to_tz = ZoneInfo(TIMEZONE_CODE_TO_NAME[to_code])
    s_time = datetime.strptime(start_time, '%H:%M:%S').time()
    e_time = datetime.strptime(end_time, '%H:%M:%S').time()
    s_dt_from = datetime.combine(date_obj, s_time).replace(tzinfo=from_tz)
    e_dt_from = datetime.combine(date_obj, e_time).replace(tzinfo=from_tz)
    s_dt_to = s_dt_from.astimezone(to_tz)
    e_dt_to = e_dt_from.astimezone(to_tz)
    return (
        s_dt_to.date(),
        s_dt_to.strftime('%H:%M:%S'),
        e_dt_to.strftime('%H:%M:%S'),
    )


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


def _split_slots_by_block_minutes(slots, block_minutes):
    if block_minutes <= 0:
        return slots

    out = []
    for slot in slots:
        start_dt = datetime.strptime(slot['start_time'], '%H:%M:%S')
        end_dt = datetime.strptime(slot['end_time'], '%H:%M:%S')
        cursor = start_dt
        while cursor + timedelta(minutes=block_minutes) <= end_dt:
            next_dt = cursor + timedelta(minutes=block_minutes)
            out.append(
                {
                    'start_time': cursor.strftime('%H:%M:%S'),
                    'end_time': next_dt.strftime('%H:%M:%S'),
                    'label': _format_label(cursor, next_dt),
                }
            )
            cursor = next_dt
    return out


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
        block_minutes_raw = request.data.get('booking_block_minutes', 30)
        try:
            duration_days = max(1, min(90, int(duration_days_raw)))
        except (TypeError, ValueError):
            duration_days = 7
        try:
            booking_block_minutes = int(block_minutes_raw)
            if booking_block_minutes not in {15, 20, 30, 45, 60, 90, 120}:
                booking_block_minutes = 30
        except (TypeError, ValueError):
            booking_block_minutes = 30

        ShareLink.objects.filter(is_active=True).update(is_active=False)
        link = ShareLink.objects.create(
            uuid=str(uuid4()),
            title=title,
            duration_days=duration_days,
            booking_block_minutes=booking_block_minutes,
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

        timezone_code = _normalize_timezone_code(request.query_params.get('timezone', 'PT'))
        base_timezone_code = _base_timezone_code()
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
        availability_map = calculate_availability_for_dates(dates, base_timezone_code)

        rows = []
        for date_obj in dates:
            date_key = date_obj.strftime('%Y-%m-%d')
            availability_item = availability_map.get(date_key)
            raw_text = availability_item['availability'] if availability_item else None
            base_slots = _filter_booked_slots(link, date_obj, _parse_slot_ranges(raw_text))
            base_slots = _split_slots_by_block_minutes(base_slots, int(link.booking_block_minutes or 30))
            slots = _convert_slots_between_timezones(
                date_obj,
                base_slots,
                base_timezone_code,
                timezone_code,
            )
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
                'booking_block_minutes': int(link.booking_block_minutes or 30),
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
        timezone_code = _normalize_timezone_code(request.data.get('timezone') or 'PT')
        base_timezone_code = _base_timezone_code()

        if not name or not email or not date_str or not start_time or not end_time:
            return Response({'error': 'name, email, date, start_time, and end_time are required.'}, status=400)

        try:
            booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

        availability_map = calculate_availability_for_dates([booking_date], base_timezone_code)
        availability_item = availability_map.get(date_str)
        base_slots = _filter_booked_slots(
            link,
            booking_date,
            _parse_slot_ranges(availability_item['availability'] if availability_item else None),
        )
        slots = _convert_slots_between_timezones(
            booking_date,
            base_slots,
            base_timezone_code,
            timezone_code,
        )
        matched_slot = any(slot['start_time'] == start_time and slot['end_time'] == end_time for slot in slots)
        if not matched_slot:
            return Response({'error': 'Selected slot is no longer available. Please refresh and pick another.'}, status=409)

        normalized_date, normalized_start_time, normalized_end_time = _convert_slot_to_base(
            booking_date,
            start_time,
            end_time,
            timezone_code,
            base_timezone_code,
        )

        booking = PublicBooking.objects.create(
            share_link=link,
            name=name,
            email=email,
            date=normalized_date,
            start_time=normalized_start_time,
            end_time=normalized_end_time,
            timezone=timezone_code,
            notes=notes,
        )

        Event.objects.create(
            name=f'Booking - {name}',
            date=normalized_date,
            start_time=normalized_start_time,
            end_time=normalized_end_time,
            timezone=base_timezone_code,
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
