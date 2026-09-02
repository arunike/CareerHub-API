import json
from io import BytesIO
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from django.core.cache import cache
from django.core import mail
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import Event, PublicBooking, ShareLink, UserSettings


def available_9_to_10(dates, timezone_code, user=None):
    return {
        item.strftime('%Y-%m-%d'): {
            'date': item.strftime('%Y-%m-%d'),
            'availability': '9:00 AM - 10:00 AM',
        }
        for item in dates
    }

