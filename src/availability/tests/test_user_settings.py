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


class UserSettingsNavigationTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='sanzhang',
            email='sanzhang@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)
        self.current_settings_url = '/api/user-settings/current/'

    def test_current_settings_saves_mobile_toolbar_items_in_order(self):
        toolbar_items = ['/applications', '__smart__', '/tasks', '/analytics']

        response = self.client.put(
            self.current_settings_url,
            {'mobile_toolbar_items': toolbar_items},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['mobile_toolbar_items'], toolbar_items)
        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.mobile_toolbar_items, toolbar_items)

    def test_current_settings_rejects_invalid_mobile_toolbar_items(self):
        invalid_values = [
            ['/applications'] * 5,
            ['/applications', '/applications'],
            ['/not-a-page'],
        ]

        for toolbar_items in invalid_values:
            with self.subTest(toolbar_items=toolbar_items):
                response = self.client.put(
                    self.current_settings_url,
                    {'mobile_toolbar_items': toolbar_items},
                    format='json',
                )

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn('mobile_toolbar_items', response.data)


class DrivingDefaultsSettingsTests(APITestCase):
    """MPG and pump price belong to the person, not to one offer, so they live here and."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='chriswong',
            email='chriswong@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)
        self.current_settings_url = '/api/user-settings/current/'

    def test_current_settings_exposes_driving_defaults(self):
        response = self.client.get(self.current_settings_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Present from the start, so the first offer priced by fuel has figures to use.
        self.assertEqual(Decimal(str(response.data['default_mpg'])), Decimal('28'))
        self.assertEqual(
            Decimal(str(response.data['default_gas_price_per_gallon'])), Decimal('4')
        )

    def test_current_settings_saves_driving_defaults(self):
        response = self.client.put(
            self.current_settings_url,
            {'default_mpg': 31.5, 'default_gas_price_per_gallon': 5.29},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.default_mpg, Decimal('31.5'))
        self.assertEqual(settings.default_gas_price_per_gallon, Decimal('5.29'))
