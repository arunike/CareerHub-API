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


def _base_timezone(user):
    cache_key = get_user_settings_tz_cache_key(getattr(user, 'id', None))
    cached = cache.get(cache_key)
    if cached:
        return normalize_timezone(cached)
    user_settings = UserSettings.objects.filter(user=user).first()
    tz_name = normalize_timezone(user_settings.primary_timezone) if user_settings else DEFAULT_TIMEZONE
    cache.set(cache_key, tz_name, timeout=600)
    return tz_name


def _format_label(start_dt, end_dt):
    start_str = start_dt.strftime('%I:%M %p').lstrip('0')
    end_str = end_dt.strftime('%I:%M %p').lstrip('0')
    return f'{start_str} - {end_str}'


def _convert_slots_between_timezones(date_obj, slots, from_timezone, to_timezone):
    from_timezone = normalize_timezone(from_timezone)
    to_timezone = normalize_timezone(to_timezone)
    if from_timezone == to_timezone:
        out = []
        for slot in slots:
            start_dt = datetime.strptime(slot['start_time'], '%H:%M:%S')
            end_dt = datetime.strptime(slot['end_time'], '%H:%M:%S')
            out.append(
                {
                    'date': date_obj.strftime('%Y-%m-%d'),
                    'start_time': slot['start_time'],
                    'end_time': slot['end_time'],
                    'label': _format_label(start_dt, end_dt),
                }
            )
        return out

    from_tz = ZoneInfo(from_timezone)
    to_tz = ZoneInfo(to_timezone)
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
                'date': s_dt_to.date().strftime('%Y-%m-%d'),
                'start_time': s_dt_to.strftime('%H:%M:%S'),
                'end_time': e_dt_to.strftime('%H:%M:%S'),
                'label': _format_label(s_dt_to, e_dt_to),
            }
        )
    return converted


def _convert_slot_to_base(date_obj, start_time, end_time, from_timezone, to_timezone):
    from_tz = ZoneInfo(normalize_timezone(from_timezone))
    to_tz = ZoneInfo(normalize_timezone(to_timezone))
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
