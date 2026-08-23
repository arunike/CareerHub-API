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


def _booking_manage_url(request, booking, action):
    path = f'/book/{booking.share_link.uuid}/{booking.uuid}/{action}'
    frontend_base_url = getattr(django_settings, 'PUBLIC_FRONTEND_BASE_URL', '')
    if frontend_base_url:
        return f'{frontend_base_url}{path}'
    return request.build_absolute_uri(path)


def _booking_api_url(request, booking, suffix):
    return request.build_absolute_uri(f'/api/booking/{booking.share_link.uuid}/manage/{booking.uuid}/{suffix}/')


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
    if booking.cancel_reason:
        body_lines.extend(['', 'Cancel reason:', booking.cancel_reason])
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
        reply_to=[booking.email],
    )
    email.attach(f'careerhub-booking-{booking.uuid}.ics', _generate_booking_ics(booking), 'text/calendar')
    email.send(fail_silently=True)
