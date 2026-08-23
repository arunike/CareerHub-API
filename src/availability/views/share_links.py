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

from .booking_validation import _serialize_booking


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
        host_email_error = _validate_public_email(host_email, 'host email')
        if host_email_error:
            return Response({'error': host_email_error}, status=status.HTTP_400_BAD_REQUEST)

        duration_days_raw = request.data.get('duration_days', 7)
        block_minutes_raw = request.data.get('booking_block_minutes', 30)
        buffer_minutes_raw = request.data.get('buffer_minutes', 0)
        max_bookings_raw = request.data.get('max_bookings_per_day', 0)
        deadline_hours_raw = request.data.get('reschedule_cancel_deadline_hours', 0)
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
        try:
            reschedule_cancel_deadline_hours = max(0, min(168, int(deadline_hours_raw)))
        except (TypeError, ValueError):
            reschedule_cancel_deadline_hours = 0

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
            reschedule_cancel_deadline_hours=reschedule_cancel_deadline_hours,
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
