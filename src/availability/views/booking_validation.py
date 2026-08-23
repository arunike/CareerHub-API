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

from .booking_notifications import (
    _booking_api_url,
    _booking_manage_url,
    _send_host_booking_email,
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


def _booking_change_deadline_error(booking):
    deadline_hours = int(booking.share_link.reschedule_cancel_deadline_hours or 0)
    if deadline_hours <= 0:
        return ''

    base_timezone = _base_timezone(booking.share_link.user)
    start_time = datetime.strptime(booking.start_time, '%H:%M:%S').time()
    starts_at = datetime.combine(booking.date, start_time).replace(tzinfo=ZoneInfo(base_timezone))
    deadline = starts_at - timedelta(hours=deadline_hours)
    if timezone.now() >= deadline:
        return f'This booking can only be rescheduled or canceled at least {deadline_hours} hours before the start time.'
    return ''


def _cancel_public_booking(request, booking, cancel_reason=''):
    booking.status = PublicBooking.STATUS_CANCELED
    booking.cancel_reason = cancel_reason.strip()[:1000]
    booking.save(update_fields=['status', 'cancel_reason'])
    if booking.event_id:
        booking.event.delete()
        booking.event = None
        booking.save(update_fields=['event'])
    _send_host_booking_email(request, booking, 'canceled')
    return booking


def _serialize_booking(request, booking):
    return PublicBookingSerializer(booking, context={'request': request}).data


