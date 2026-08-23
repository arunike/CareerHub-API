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


def _validate_public_email(value, label='email'):
    try:
        validate_email(value)
    except ValidationError:
        return f'Please enter a valid {label}.'
    return ''


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
