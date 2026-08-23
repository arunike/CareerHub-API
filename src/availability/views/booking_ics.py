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

from .booking_intake import _format_public_booking_notes
from .booking_slots import _base_timezone


def _ics_escape(value):
    return str(value or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def _generate_booking_ics(booking):
    tz_name = normalize_timezone(
        booking.event.timezone if booking.event_id else _base_timezone(booking.share_link.user)
    )
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
