from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

from django.conf import settings as django_settings
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Event, PublicBooking, ShareLink, UserSettings
from ..serializers import PublicBookingSerializer, ShareLinkSerializer
from ..throttling import PublicBookingCreateThrottle, PublicBookingSlotsThrottle
from ..utils import calculate_availability_for_dates
from ..signals import get_user_settings_tz_cache_key

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


def _base_timezone_code(user):
    cache_key = get_user_settings_tz_cache_key(getattr(user, 'id', None))
    cached = cache.get(cache_key)
    if cached:
        return cached
    user_settings = UserSettings.objects.filter(user=user).first()
    tz_code = _normalize_timezone_code(user_settings.primary_timezone) if user_settings else 'PT'
    cache.set(cache_key, tz_code, timeout=600)
    return tz_code


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
    if not link or link.user_id is None:
        return None
    if link.expires_at <= timezone.now():
        link.is_active = False
        link.save(update_fields=['is_active'])
        return None
    return link


def _get_share_link_for_existing_booking(uuid_value, booking_uuid):
    if not booking_uuid:
        return None
    link = ShareLink.objects.filter(uuid=uuid_value).first()
    if not link or link.user_id is None:
        return None
    if not PublicBooking.objects.filter(share_link=link, uuid=booking_uuid).exists():
        return None
    return link


def _filter_booked_slots(link, date_obj, slots):
    bookings = (
        PublicBooking.objects
        .filter(share_link=link, date=date_obj, status=PublicBooking.STATUS_ACTIVE)
        .values_list('start_time', 'end_time')
    )
    buffer_minutes = max(0, int(link.buffer_minutes or 0))
    available = []
    for slot in slots:
        slot_start = datetime.strptime(slot['start_time'], '%H:%M:%S')
        slot_end = datetime.strptime(slot['end_time'], '%H:%M:%S')
        is_blocked = False
        for booking_start_raw, booking_end_raw in bookings:
            booking_start = datetime.strptime(booking_start_raw, '%H:%M:%S') - timedelta(minutes=buffer_minutes)
            booking_end = datetime.strptime(booking_end_raw, '%H:%M:%S') + timedelta(minutes=buffer_minutes)
            if slot_start < booking_end and slot_end > booking_start:
                is_blocked = True
                break
        if not is_blocked:
            available.append(slot)
    return available


def _has_reached_daily_limit(link, date_obj):
    max_per_day = int(link.max_bookings_per_day or 0)
    if max_per_day <= 0:
        return False
    return (
        PublicBooking.objects
        .filter(share_link=link, date=date_obj, status=PublicBooking.STATUS_ACTIVE)
        .count()
        >= max_per_day
    )


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


def _normalize_intake_questions(value):
    if not isinstance(value, list):
        return []
    questions = []
    for index, item in enumerate(value[:10]):
        if not isinstance(item, dict):
            continue
        label = str(item.get('label') or '').strip()
        if not label:
            continue
        question_id = str(item.get('id') or f'q_{index + 1}').strip()[:80]
        questions.append(
            {
                'id': question_id,
                'label': label[:240],
                'required': bool(item.get('required', False)),
            }
        )
    return questions


def _coerce_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {'false', '0', 'no', 'off'}


def _validate_intake_answers(questions, raw_answers):
    answers = raw_answers if isinstance(raw_answers, dict) else {}
    normalized = {}
    for question in questions:
        question_id = question['id']
        value = str(answers.get(question_id) or '').strip()
        if question.get('required') and not value:
            return None, f'{question["label"]} is required.'
        if value:
            normalized[question_id] = value[:2000]
    return normalized, None


def _format_public_booking_notes(booking, intake_answers=None):
    intake_answers = intake_answers if intake_answers is not None else booking.intake_answers
    lines = [f'Public booking via share link ({booking.email})']
    if booking.notes:
        lines.extend(['', booking.notes])
    questions = _normalize_intake_questions(booking.share_link.intake_questions)
    answer_lines = []
    for question in questions:
        answer = intake_answers.get(question['id'])
        if answer:
            answer_lines.append(f'{question["label"]}: {answer}')
    if answer_lines:
        lines.extend(['', 'Intake answers:', *answer_lines])
    return '\n'.join(lines).strip()


def _booking_manage_url(request, booking, action):
    path = f'/book/{booking.share_link.uuid}/{booking.uuid}/{action}'
    frontend_base_url = getattr(django_settings, 'PUBLIC_FRONTEND_BASE_URL', '')
    if frontend_base_url:
        return f'{frontend_base_url}{path}'
    return request.build_absolute_uri(path)


def _booking_api_url(request, booking, suffix):
    return request.build_absolute_uri(f'/api/booking/{booking.share_link.uuid}/manage/{booking.uuid}/{suffix}/')


def _ics_escape(value):
    return str(value or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def _generate_booking_ics(booking):
    timezone_code = booking.event.timezone if booking.event_id else _base_timezone_code(booking.share_link.user)
    tz_name = TIMEZONE_CODE_TO_NAME.get(_normalize_timezone_code(timezone_code), TIMEZONE_CODE_TO_NAME['PT'])
    start_dt = datetime.combine(booking.date, datetime.strptime(booking.start_time, '%H:%M:%S').time())
    end_dt = datetime.combine(booking.date, datetime.strptime(booking.end_time, '%H:%M:%S').time())
    created = booking.created_at.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    status_value = 'CANCELLED' if booking.status == PublicBooking.STATUS_CANCELED else 'CONFIRMED'
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//CareerHub//Public Booking//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        f'UID:{booking.uuid}@careerhub',
        f'DTSTAMP:{timezone.now().astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")}',
        f'CREATED:{created}',
        f'DTSTART;TZID={tz_name}:{start_dt.strftime("%Y%m%dT%H%M%S")}',
        f'DTEND;TZID={tz_name}:{end_dt.strftime("%Y%m%dT%H%M%S")}',
        f'SUMMARY:{_ics_escape(f"Booking - {booking.name}")}',
        f'DESCRIPTION:{_ics_escape(_format_public_booking_notes(booking))}',
        f'ORGANIZER;CN={_ics_escape(booking.share_link.host_display_name or "CareerHub Host")}:MAILTO:{booking.share_link.host_email or ""}',
        f'ATTENDEE;CN={_ics_escape(booking.name)};ROLE=REQ-PARTICIPANT:MAILTO:{booking.email}',
        f'STATUS:{status_value}',
        'END:VEVENT',
        'END:VCALENDAR',
        '',
    ]
    return '\r\n'.join(lines)


def _send_host_booking_email(request, booking, action):
    host_email = booking.share_link.host_email
    if not host_email:
        return
    action_label = {
        'created': 'New public booking',
        'rescheduled': 'Public booking rescheduled',
        'canceled': 'Public booking canceled',
    }.get(action, 'Public booking update')
    body_lines = [
        f'{action_label}: {booking.name}',
        '',
        f'When: {booking.date} {booking.start_time[:5]}-{booking.end_time[:5]} {booking.timezone}',
        f'Guest: {booking.name} <{booking.email}>',
        f'Booking link: {booking.share_link.title}',
    ]
    if booking.notes:
        body_lines.extend(['', 'Notes:', booking.notes])
    questions = _normalize_intake_questions(booking.share_link.intake_questions)
    intake_lines = [
        f'{question["label"]}: {booking.intake_answers.get(question["id"])}'
        for question in questions
        if booking.intake_answers.get(question['id'])
    ]
    if intake_lines:
        body_lines.extend(['', 'Intake answers:', *intake_lines])
    if booking.share_link.allow_reschedule_cancel:
        body_lines.extend(
            [
                '',
                f'Reschedule: {_booking_manage_url(request, booking, "reschedule")}',
                f'Cancel: {_booking_manage_url(request, booking, "cancel")}',
            ]
        )
    body_lines.extend(['', f'ICS: {_booking_api_url(request, booking, "ics")}'])

    email = EmailMessage(
        subject=f'CareerHub: {action_label}',
        body='\n'.join(body_lines),
        from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', None),
        to=[host_email],
    )
    email.attach(f'careerhub-booking-{booking.uuid}.ics', _generate_booking_ics(booking), 'text/calendar')
    email.send(fail_silently=True)


def _serialize_booking(request, booking):
    return PublicBookingSerializer(booking, context={'request': request}).data


def _validate_requested_slot(link, booking_date, start_time, end_time, timezone_code, exclude_booking=None):
    base_timezone_code = _base_timezone_code(link.user)
    if _has_reached_daily_limit(link, booking_date):
        if not exclude_booking or exclude_booking.date != booking_date:
            return None, 'This day has reached the booking limit. Please choose another day.'

    availability_map = calculate_availability_for_dates([booking_date], base_timezone_code, user=link.user)
    availability_item = availability_map.get(booking_date.strftime('%Y-%m-%d'))
    base_slots = _split_slots_by_block_minutes(
        _parse_slot_ranges(availability_item['availability'] if availability_item else None),
        int(link.booking_block_minutes or 30),
    )
    if exclude_booking:
        base_slots = _filter_booked_slots_excluding(link, booking_date, base_slots, exclude_booking)
    else:
        base_slots = _filter_booked_slots(link, booking_date, base_slots)
    slots = _convert_slots_between_timezones(
        booking_date,
        base_slots,
        base_timezone_code,
        timezone_code,
    )
    matched_slot = any(slot['start_time'] == start_time and slot['end_time'] == end_time for slot in slots)
    if not matched_slot:
        return None, 'Selected slot is no longer available. Please refresh and pick another.'
    return _convert_slot_to_base(booking_date, start_time, end_time, timezone_code, base_timezone_code), None


def _filter_booked_slots_excluding(link, date_obj, slots, excluded_booking):
    bookings = (
        PublicBooking.objects
        .filter(share_link=link, date=date_obj, status=PublicBooking.STATUS_ACTIVE)
        .exclude(pk=excluded_booking.pk)
        .values_list('start_time', 'end_time')
    )
    buffer_minutes = max(0, int(link.buffer_minutes or 0))
    available = []
    for slot in slots:
        slot_start = datetime.strptime(slot['start_time'], '%H:%M:%S')
        slot_end = datetime.strptime(slot['end_time'], '%H:%M:%S')
        is_blocked = False
        for booking_start_raw, booking_end_raw in bookings:
            booking_start = datetime.strptime(booking_start_raw, '%H:%M:%S') - timedelta(minutes=buffer_minutes)
            booking_end = datetime.strptime(booking_end_raw, '%H:%M:%S') + timedelta(minutes=buffer_minutes)
            if slot_start < booking_end and slot_end > booking_start:
                is_blocked = True
                break
        if not is_blocked:
            available.append(slot)
    return available


class ShareLinkViewSet(viewsets.ModelViewSet):
    queryset = ShareLink.objects.all().order_by('-created_at')
    serializer_class = ShareLinkSerializer

    def get_queryset(self):
        return ShareLink.objects.filter(user=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['get'])
    def current(self, request):
        now = timezone.now()
        self.get_queryset().filter(is_active=True, expires_at__lte=now).update(is_active=False)
        link = self.get_queryset().filter(is_active=True, expires_at__gt=now).first()
        if not link:
            return Response({'active': None})
        return Response({'active': self.get_serializer(link).data})

    @action(detail=False, methods=['post'])
    def generate(self, request):
        title = request.data.get('title') or 'My Availability'
        host_display_name = (request.data.get('host_display_name') or '').strip()
        host_email = (request.data.get('host_email') or '').strip()
        public_note = (request.data.get('public_note') or '').strip()

        if not host_display_name or not host_email:
            return Response({'error': 'Display Name and Host Email are required.'}, status=status.HTTP_400_BAD_REQUEST)

        duration_days_raw = request.data.get('duration_days', 7)
        block_minutes_raw = request.data.get('booking_block_minutes', 30)
        buffer_minutes_raw = request.data.get('buffer_minutes', 0)
        max_bookings_raw = request.data.get('max_bookings_per_day', 0)
        allow_reschedule_cancel = _coerce_bool(request.data.get('allow_reschedule_cancel'), True)
        intake_questions = _normalize_intake_questions(request.data.get('intake_questions', []))
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
        try:
            buffer_minutes = int(buffer_minutes_raw)
            if buffer_minutes not in {0, 5, 10, 15, 20, 30, 45, 60}:
                buffer_minutes = 0
        except (TypeError, ValueError):
            buffer_minutes = 0
        try:
            max_bookings_per_day = max(0, min(20, int(max_bookings_raw)))
        except (TypeError, ValueError):
            max_bookings_per_day = 0

        link = ShareLink.objects.create(
            user=request.user,
            uuid=str(uuid4()),
            title=title,
            host_display_name=host_display_name,
            host_email=host_email,
            public_note=public_note,
            duration_days=duration_days,
            booking_block_minutes=booking_block_minutes,
            buffer_minutes=buffer_minutes,
            max_bookings_per_day=max_bookings_per_day,
            allow_reschedule_cancel=allow_reschedule_cancel,
            intake_questions=intake_questions,
            expires_at=timezone.now() + timedelta(days=duration_days),
            is_active=True,
        )
        return Response(self.get_serializer(link).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def deactivate(self, request):
        now = timezone.now()
        count = self.get_queryset().filter(is_active=True, expires_at__gt=now).update(is_active=False)
        return Response({'message': f'Deactivated {count} active link(s).'})

    @action(detail=True, methods=['post'])
    def deactivate_link(self, request, pk=None):
        link = self.get_object()
        link.is_active = False
        link.save(update_fields=['is_active'])
        return Response(self.get_serializer(link).data)

    @action(detail=False, methods=['get'])
    def bookings(self, request):
        bookings = (
            PublicBooking.objects
            .filter(share_link__user=request.user)
            .select_related('share_link')
            .order_by('-date', '-start_time')
        )
        return Response(PublicBookingSerializer(bookings, many=True, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def link_bookings(self, request, pk=None):
        link = self.get_object()
        bookings = link.bookings.select_related('share_link').order_by('-date', '-start_time')
        return Response(PublicBookingSerializer(bookings, many=True, context={'request': request}).data)


class PublicBookingSlotsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PublicBookingSlotsThrottle]

    def get(self, request, uuid):
        link = _get_share_link_or_none(uuid)
        if not link:
            link = _get_share_link_for_existing_booking(uuid, request.query_params.get('booking_uuid'))
        if not link:
            return Response({'error': 'This booking link is invalid or expired.'}, status=404)

        timezone_code = _normalize_timezone_code(request.query_params.get('timezone', 'PT'))
        base_timezone_code = _base_timezone_code(link.user)
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
        availability_map = calculate_availability_for_dates(dates, base_timezone_code, user=link.user)

        rows = []
        for date_obj in dates:
            date_key = date_obj.strftime('%Y-%m-%d')
            availability_item = availability_map.get(date_key)
            raw_text = availability_item['availability'] if availability_item else None
            if _has_reached_daily_limit(link, date_obj):
                base_slots = []
            else:
                base_slots = _split_slots_by_block_minutes(_parse_slot_ranges(raw_text), int(link.booking_block_minutes or 30))
                base_slots = _filter_booked_slots(link, date_obj, base_slots)
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

        user_settings = UserSettings.objects.filter(user=link.user).first()
        host_profile_picture = request.build_absolute_uri(user_settings.profile_picture.url) if user_settings and user_settings.profile_picture else None

        return Response(
            {
                'title': link.title,
                'host_display_name': link.host_display_name,
                'host_email': link.host_email,
                'host_profile_picture': host_profile_picture,
                'public_note': link.public_note,
                'expires_at': link.expires_at,
                'timezone': timezone_code,
                'booking_block_minutes': int(link.booking_block_minutes or 30),
                'buffer_minutes': int(link.buffer_minutes or 0),
                'max_bookings_per_day': int(link.max_bookings_per_day or 0),
                'allow_reschedule_cancel': link.allow_reschedule_cancel,
                'intake_questions': _normalize_intake_questions(link.intake_questions),
                'days': rows,
            }
        )


class PublicBookingCreateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PublicBookingCreateThrottle]

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
        intake_answers, intake_error = _validate_intake_answers(
            _normalize_intake_questions(link.intake_questions),
            request.data.get('intake_answers', {}),
        )
        if intake_error:
            return Response({'error': intake_error}, status=400)

        if not name or not email or not date_str or not start_time or not end_time:
            return Response({'error': 'name, email, date, start_time, and end_time are required.'}, status=400)

        try:
            booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

        normalized_slot, slot_error = _validate_requested_slot(link, booking_date, start_time, end_time, timezone_code)
        if slot_error:
            return Response({'error': slot_error}, status=409)
        normalized_date, normalized_start_time, normalized_end_time = normalized_slot
        base_timezone_code = _base_timezone_code(link.user)

        event = Event.objects.create(
            user=link.user,
            name=f'Booking - {name}',
            date=normalized_date,
            start_time=normalized_start_time,
            end_time=normalized_end_time,
            timezone=base_timezone_code,
            location_type='virtual',
            notes='',
            is_locked=True,
        )
        booking = PublicBooking.objects.create(
            share_link=link,
            event=event,
            name=name,
            email=email,
            date=normalized_date,
            start_time=normalized_start_time,
            end_time=normalized_end_time,
            timezone=timezone_code,
            notes=notes,
            intake_answers=intake_answers or {},
        )
        event.notes = _format_public_booking_notes(booking)
        event.save(update_fields=['notes', 'updated_at'])
        _send_host_booking_email(request, booking, 'created')

        return Response(
            {
                'message': 'Booking confirmed.',
                'booking': _serialize_booking(request, booking),
            },
            status=status.HTTP_201_CREATED,
        )

class PublicBookingViewSet(viewsets.ModelViewSet):
    serializer_class = PublicBookingSerializer

    def get_queryset(self):
        return (
            PublicBooking.objects
            .filter(share_link__user=self.request.user)
            .select_related('share_link')
            .order_by('-date', '-start_time')
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This booking is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if instance.event_id:
            instance.event.delete()
        return super().destroy(request, *args, **kwargs)


class PublicBookingManageView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PublicBookingCreateThrottle]

    def _get_booking(self, uuid, booking_uuid):
        link = ShareLink.objects.filter(uuid=uuid, user__isnull=False).first()
        if not link:
            return None
        return (
            PublicBooking.objects
            .filter(share_link=link, uuid=booking_uuid)
            .select_related('share_link', 'event')
            .first()
        )

    def get(self, request, uuid, booking_uuid, action):
        booking = self._get_booking(uuid, booking_uuid)
        if not booking:
            return Response({'error': 'This booking link is invalid or expired.'}, status=404)
        if action == 'ics':
            response = HttpResponse(_generate_booking_ics(booking), content_type='text/calendar; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="careerhub-booking-{booking.uuid}.ics"'
            return response
        if action == 'details':
            return Response(
                {
                    'booking': _serialize_booking(request, booking),
                    'share_link': ShareLinkSerializer(booking.share_link, context={'request': request}).data,
                }
            )
        return Response({'error': 'Unsupported action.'}, status=400)

    def post(self, request, uuid, booking_uuid, action):
        booking = self._get_booking(uuid, booking_uuid)
        if not booking:
            return Response({'error': 'This booking link is invalid or expired.'}, status=404)
        if not booking.share_link.allow_reschedule_cancel:
            return Response({'error': 'This booking cannot be changed from the public link.'}, status=403)
        if booking.status == PublicBooking.STATUS_CANCELED:
            return Response({'error': 'This booking has already been canceled.'}, status=409)

        if action == 'cancel':
            booking.status = PublicBooking.STATUS_CANCELED
            booking.save(update_fields=['status'])
            if booking.event_id:
                booking.event.delete()
                booking.event = None
                booking.save(update_fields=['event'])
            _send_host_booking_email(request, booking, 'canceled')
            return Response({'message': 'Booking canceled.', 'booking': _serialize_booking(request, booking)})

        if action != 'reschedule':
            return Response({'error': 'Unsupported action.'}, status=400)

        date_str = request.data.get('date')
        start_time = request.data.get('start_time')
        end_time = request.data.get('end_time')
        timezone_code = _normalize_timezone_code(request.data.get('timezone') or booking.timezone or 'PT')
        if not date_str or not start_time or not end_time:
            return Response({'error': 'date, start_time, and end_time are required.'}, status=400)
        try:
            booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

        normalized_slot, slot_error = _validate_requested_slot(
            booking.share_link,
            booking_date,
            start_time,
            end_time,
            timezone_code,
            exclude_booking=booking,
        )
        if slot_error:
            return Response({'error': slot_error}, status=409)

        normalized_date, normalized_start_time, normalized_end_time = normalized_slot
        base_timezone_code = _base_timezone_code(booking.share_link.user)
        booking.date = normalized_date
        booking.start_time = normalized_start_time
        booking.end_time = normalized_end_time
        booking.timezone = timezone_code
        booking.save(update_fields=['date', 'start_time', 'end_time', 'timezone'])

        if booking.event_id:
            event = booking.event
            event.date = normalized_date
            event.start_time = normalized_start_time
            event.end_time = normalized_end_time
            event.timezone = base_timezone_code
            event.notes = _format_public_booking_notes(booking)
            event.save(update_fields=['date', 'start_time', 'end_time', 'timezone', 'notes', 'updated_at'])
        else:
            event = Event.objects.create(
                user=booking.share_link.user,
                name=f'Booking - {booking.name}',
                date=normalized_date,
                start_time=normalized_start_time,
                end_time=normalized_end_time,
                timezone=base_timezone_code,
                location_type='virtual',
                notes=_format_public_booking_notes(booking),
                is_locked=True,
            )
            booking.event = event
            booking.save(update_fields=['event'])

        _send_host_booking_email(request, booking, 'rescheduled')
        return Response({'message': 'Booking rescheduled.', 'booking': _serialize_booking(request, booking)})
