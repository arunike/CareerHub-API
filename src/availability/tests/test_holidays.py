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

from availability.models import CustomHoliday, Event, PublicBooking, ShareLink, UserSettings


def available_9_to_10(dates, timezone_code, user=None):
    return {
        item.strftime('%Y-%m-%d'): {
            'date': item.strftime('%Y-%m-%d'),
            'availability': '9:00 AM - 10:00 AM',
        }
        for item in dates
    }



class HolidayDeletionTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username='holiday-delete-user',
            email='holiday-delete@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)

    def test_deletes_a_day_still_carrying_the_retired_lock_flag(self):
        holiday = CustomHoliday.objects.create(
            user=self.user, date='2026-07-01', description='Time off', is_locked=True
        )

        response = self.client.delete(f'/api/holidays/{holiday.id}/')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CustomHoliday.objects.filter(id=holiday.id).exists())

    def test_delete_all_clears_every_custom_day_and_keeps_the_observed_ones(self):
        CustomHoliday.objects.create(
            user=self.user, date='2026-07-01', description='Time off', is_locked=True
        )
        observed = CustomHoliday.objects.create(
            user=self.user,
            date='2026-10-01',
            description='Observed Day A',
            holiday_type='observed',
        )

        response = self.client.delete('/api/holidays/delete_all/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            list(CustomHoliday.objects.filter(user=self.user).values_list('id', flat=True)),
            [observed.id],
        )
