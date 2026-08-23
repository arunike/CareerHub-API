from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch


from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import UserSettings


def available_9_to_10(dates, timezone_code, user=None):
    return {
        item.strftime('%Y-%m-%d'): {
            'date': item.strftime('%Y-%m-%d'),
            'availability': '9:00 AM - 10:00 AM',
        }
        for item in dates
    }


class AvailabilityRangeTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='availability-host',
            email='availability@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)

    @patch('availability.views.availability.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_generate_defaults_to_two_weeks(self, _mock_availability):
        response = self.client.get('/api/availability/generate/?start_date=2026-05-04')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 14)

    @patch('availability.views.availability.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_generate_uses_saved_or_requested_week_range(self, _mock_availability):
        UserSettings.objects.create(user=self.user, availability_weeks=16)

        saved_response = self.client.get('/api/availability/generate/?start_date=2026-05-04')
        requested_response = self.client.get('/api/availability/generate/?start_date=2026-05-04&weeks=1')

        self.assertEqual(saved_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(saved_response.data), 112)
        self.assertEqual(requested_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(requested_response.data), 7)

    @patch(
        'availability.utils.timezone.now',
        return_value=datetime(2026, 6, 3, 19, 0, tzinfo=dt_timezone.utc),
    )
    def test_generate_hides_elapsed_time_blocks_for_today(self, _mock_now):
        UserSettings.objects.create(
            user=self.user,
            work_time_ranges=[
                {'start': '11:00:00', 'end': '12:00:00'},
                {'start': '14:00:00', 'end': '17:00:00'},
            ],
        )

        response = self.client.get(
            '/api/availability/generate/?start_date=2026-06-03&weeks=1&timezone=America/Los_Angeles'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        today = next(item for item in response.data if item['date'] == '2026-06-03')
        self.assertEqual(today['availability'], '2:00 PM - 5:00 PM')

    @patch(
        'availability.utils.timezone.now',
        return_value=datetime(2026, 6, 3, 21, 0, tzinfo=dt_timezone.utc),
    )
    def test_generate_keeps_future_part_of_active_time_block_for_today(self, _mock_now):
        UserSettings.objects.create(
            user=self.user,
            work_time_ranges=[
                {'start': '14:00:00', 'end': '17:00:00'},
            ],
        )

        response = self.client.get(
            '/api/availability/generate/?start_date=2026-06-03&weeks=1&timezone=America/Los_Angeles'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        today = next(item for item in response.data if item['date'] == '2026-06-03')
        self.assertEqual(today['availability'], '2:30 PM - 5:00 PM')

    @patch(
        'availability.utils.timezone.now',
        return_value=datetime(2026, 6, 1, 7, 0, tzinfo=dt_timezone.utc),
    )
    def test_generate_uses_day_specific_time_ranges(self, _mock_now):
        UserSettings.objects.create(
            user=self.user,
            work_days=[0, 1, 2, 3, 4],
            work_time_ranges=[
                {'days': [0, 1, 2, 3], 'start': '10:00:00', 'end': '15:00:00'},
                {'days': [4], 'start': '13:00:00', 'end': '16:00:00'},
            ],
        )

        response = self.client.get(
            '/api/availability/generate/?start_date=2026-06-01&weeks=1&timezone=America/Los_Angeles'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_date = {item['date']: item['availability'] for item in response.data}
        self.assertEqual(by_date['2026-06-01'], '10:00 AM - 3:00 PM')
        self.assertEqual(by_date['2026-06-02'], '10:00 AM - 3:00 PM')
        self.assertEqual(by_date['2026-06-05'], '1:00 PM - 4:00 PM')

    @patch(
        'availability.utils.timezone.now',
        return_value=datetime(2026, 6, 4, 1, 57, tzinfo=dt_timezone.utc),
    )
    def test_generate_hides_today_when_all_time_blocks_elapsed(self, _mock_now):
        UserSettings.objects.create(
            user=self.user,
            work_time_ranges=[
                {'start': '11:00:00', 'end': '12:00:00'},
                {'start': '14:00:00', 'end': '17:00:00'},
            ],
        )

        response = self.client.get(
            '/api/availability/generate/?start_date=2026-06-03&weeks=1&timezone=America/Los_Angeles'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('2026-06-03', [item['date'] for item in response.data])
