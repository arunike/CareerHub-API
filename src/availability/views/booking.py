from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

from django.conf import settings as django_settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
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
from ..timezones import DEFAULT_TIMEZONE, normalize_timezone
from ..utils import calculate_availability_for_dates
from ..signals import get_user_settings_tz_cache_key

from .booking_slots import (
    _base_timezone,
    _convert_slot_to_base,
    _convert_slots_between_timezones,
    _filter_booked_slots,
    _format_label,
    _has_reached_daily_limit,
    _parse_slot_ranges,
    _split_slots_by_block_minutes,
)
from .booking_intake import (
    _coerce_bool,
    _format_public_booking_notes,
    _normalize_intake_questions,
    _validate_intake_answers,
    _validate_public_email,
)
from .booking_ics import _generate_booking_ics

from .booking_notifications import _booking_api_url, _booking_manage_url, _send_host_booking_email
from .booking_validation import (
    _booking_change_deadline_error,
    _cancel_public_booking,
    _get_share_link_for_existing_booking,
    _get_share_link_or_none,
    _serialize_booking,
)


def _validate_requested_slot(link, booking_date, start_time, end_time, timezone_name, exclude_booking=None):
    base_timezone = _base_timezone(link.user)
    target_date_key = booking_date.strftime('%Y-%m-%d')
    base_dates = [booking_date - timedelta(days=1), booking_date, booking_date + timedelta(days=1)]
    availability_map = calculate_availability_for_dates(base_dates, base_timezone, user=link.user)

    for base_date in base_dates:
        if _has_reached_daily_limit(link, base_date):
            if not exclude_booking or exclude_booking.date != base_date:
                continue

        availability_item = availability_map.get(base_date.strftime('%Y-%m-%d'))
        base_slots = _split_slots_by_block_minutes(
            _parse_slot_ranges(availability_item['availability'] if availability_item else None),
            int(link.booking_block_minutes or 30),
        )
        if exclude_booking:
            base_slots = _filter_booked_slots_excluding(link, base_date, base_slots, exclude_booking)
        else:
            base_slots = _filter_booked_slots(link, base_date, base_slots)
        slots = _convert_slots_between_timezones(
            base_date,
            base_slots,
            base_timezone,
            timezone_name,
        )
        for slot in slots:
            if (
                slot['date'] == target_date_key
                and slot['start_time'] == start_time
                and slot['end_time'] == end_time
            ):
                return _convert_slot_to_base(booking_date, start_time, end_time, timezone_name, base_timezone), None

    return None, 'Selected slot is no longer available. Please refresh and pick another.'


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

        timezone_name = normalize_timezone(request.query_params.get('timezone'))
        base_timezone = _base_timezone(link.user)
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

        target_dates = [start_date + timedelta(days=i) for i in range(days)]
        base_dates = [start_date - timedelta(days=1) + timedelta(days=i) for i in range(days + 2)]
        availability_map = calculate_availability_for_dates(base_dates, base_timezone, user=link.user)

        rows_by_date = {
            date_obj.strftime('%Y-%m-%d'): {
                'date': date_obj.strftime('%Y-%m-%d'),
                'day_name': date_obj.strftime('%A'),
                'readable_date': date_obj.strftime('%b %d'),
                'slots': [],
            }
            for date_obj in target_dates
        }

        for base_date in base_dates:
            date_key = base_date.strftime('%Y-%m-%d')
            availability_item = availability_map.get(date_key)
            raw_text = availability_item['availability'] if availability_item else None
            if _has_reached_daily_limit(link, base_date):
                base_slots = []
            else:
                base_slots = _split_slots_by_block_minutes(_parse_slot_ranges(raw_text), int(link.booking_block_minutes or 30))
                base_slots = _filter_booked_slots(link, base_date, base_slots)
            slots = _convert_slots_between_timezones(
                base_date,
                base_slots,
                base_timezone,
                timezone_name,
            )
            for slot in slots:
                target_row = rows_by_date.get(slot['date'])
                if target_row is not None:
                    target_row['slots'].append(
                        {
                            'start_time': slot['start_time'],
                            'end_time': slot['end_time'],
                            'label': slot['label'],
                        }
                    )

        rows = list(rows_by_date.values())

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
                'timezone': timezone_name,
                'booking_block_minutes': int(link.booking_block_minutes or 30),
                'buffer_minutes': int(link.buffer_minutes or 0),
                'max_bookings_per_day': int(link.max_bookings_per_day or 0),
                'allow_reschedule_cancel': link.allow_reschedule_cancel,
                'reschedule_cancel_deadline_hours': int(link.reschedule_cancel_deadline_hours or 0),
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
        timezone_name = normalize_timezone(request.data.get('timezone'))
        intake_answers, intake_error = _validate_intake_answers(
            _normalize_intake_questions(link.intake_questions),
            request.data.get('intake_answers', {}),
        )
        if intake_error:
            return Response({'error': intake_error}, status=400)

        if not name or not email or not date_str or not start_time or not end_time:
            return Response({'error': 'name, email, date, start_time, and end_time are required.'}, status=400)
        email_error = _validate_public_email(email)
        if email_error:
            return Response({'error': email_error}, status=400)

        try:
            booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

        normalized_slot, slot_error = _validate_requested_slot(link, booking_date, start_time, end_time, timezone_name)
        if slot_error:
            return Response({'error': slot_error}, status=409)
        normalized_date, normalized_start_time, normalized_end_time = normalized_slot
        base_timezone = _base_timezone(link.user)

        event = Event.objects.create(
            user=link.user,
            name=f'Booking - {name}',
            date=normalized_date,
            start_time=normalized_start_time,
            end_time=normalized_end_time,
            timezone=base_timezone,
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
            timezone=timezone_name,
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

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        if booking.status == PublicBooking.STATUS_CANCELED:
            return Response({'error': 'This booking has already been canceled.'}, status=409)
        cancel_reason = request.data.get('cancel_reason') or 'Canceled by host.'
        _cancel_public_booking(request, booking, cancel_reason)
        return Response({'message': 'Booking canceled by host.', 'booking': _serialize_booking(request, booking)})


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
        deadline_error = _booking_change_deadline_error(booking)
        if deadline_error:
            return Response({'error': deadline_error}, status=403)

        if action == 'cancel':
            cancel_reason = (request.data.get('cancel_reason') or '').strip()[:1000]
            _cancel_public_booking(request, booking, cancel_reason)
            return Response({'message': 'Booking canceled.', 'booking': _serialize_booking(request, booking)})

        if action != 'reschedule':
            return Response({'error': 'Unsupported action.'}, status=400)

        date_str = request.data.get('date')
        start_time = request.data.get('start_time')
        end_time = request.data.get('end_time')
        timezone_name = normalize_timezone(request.data.get('timezone') or booking.timezone)
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
            timezone_name,
            exclude_booking=booking,
        )
        if slot_error:
            return Response({'error': slot_error}, status=409)

        normalized_date, normalized_start_time, normalized_end_time = normalized_slot
        base_timezone = _base_timezone(booking.share_link.user)
        booking.date = normalized_date
        booking.start_time = normalized_start_time
        booking.end_time = normalized_end_time
        booking.timezone = timezone_name
        booking.save(update_fields=['date', 'start_time', 'end_time', 'timezone'])

        if booking.event_id:
            event = booking.event
            event.date = normalized_date
            event.start_time = normalized_start_time
            event.end_time = normalized_end_time
            event.timezone = base_timezone
            event.notes = _format_public_booking_notes(booking)
            event.save(update_fields=['date', 'start_time', 'end_time', 'timezone', 'notes', 'updated_at'])
        else:
            event = Event.objects.create(
                user=booking.share_link.user,
                name=f'Booking - {booking.name}',
                date=normalized_date,
                start_time=normalized_start_time,
                end_time=normalized_end_time,
                timezone=base_timezone,
                location_type='virtual',
                notes=_format_public_booking_notes(booking),
                is_locked=True,
            )
            booking.event = event
            booking.save(update_fields=['event'])

        _send_host_booking_email(request, booking, 'rescheduled')
        return Response({'message': 'Booking rescheduled.', 'booking': _serialize_booking(request, booking)})
