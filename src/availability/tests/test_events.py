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


class EventFeedPaginationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username='event-feed-user',
            email='event-feed@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)

    def test_feed_paginates_all_regular_events_without_a_fixed_date_window(self):
        Event.objects.create(
            user=self.user,
            name='Old event',
            date='2024-01-10',
            start_time='09:00:00',
            end_time='10:00:00',
        )
        Event.objects.create(
            user=self.user,
            name='Middle event',
            date='2025-01-10',
            start_time='09:00:00',
            end_time='10:00:00',
        )
        Event.objects.create(
            user=self.user,
            name='Future event',
            date='2027-01-10',
            start_time='09:00:00',
            end_time='10:00:00',
        )

        response = self.client.get(
            '/api/events/feed/',
            {'page': 2, 'page_size': 2, 'year': 'all', 'sort_order': 'asc'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual([item['name'] for item in response.data['results']], ['Future event'])


class EventEndDateValidationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username='span-user',
            email='span-user@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)

    def _payload(self, **overrides):
        payload = {
            'name': 'Offsite',
            'date': '2026-03-10',
            'start_time': '09:00:00',
            'end_time': '17:00:00',
        }
        payload.update(overrides)
        return payload

    def test_rejects_end_date_before_start_date(self):
        response = self.client.post(
            '/api/events/', self._payload(end_date='2026-03-09'), format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('end_date', response.data)

    def test_allows_end_date_equal_to_or_after_start_date(self):
        same_day = self.client.post(
            '/api/events/', self._payload(end_date='2026-03-10'), format='json'
        )
        self.assertEqual(same_day.status_code, status.HTTP_201_CREATED)

        # A separate week, so the overlap check does not mask the range check.
        multi_day = self.client.post(
            '/api/events/',
            self._payload(name='Offsite II', date='2026-04-10', end_date='2026-04-12'),
            format='json',
        )
        self.assertEqual(multi_day.status_code, status.HTTP_201_CREATED, multi_day.data)

    def test_patching_start_past_a_stored_end_date_is_rejected(self):
        created = self.client.post(
            '/api/events/', self._payload(end_date='2026-03-12'), format='json'
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        # Only the start moves, so the check has to fall back to the stored end date.
        response = self.client.patch(
            f'/api/events/{created.data["id"]}/', {'date': '2026-03-20'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('end_date', response.data)

    def test_clearing_end_date_shortens_the_event(self):
        created = self.client.post(
            '/api/events/', self._payload(end_date='2026-03-12'), format='json'
        )
        response = self.client.patch(
            f'/api/events/{created.data["id"]}/', {'end_date': None}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['end_date'])
