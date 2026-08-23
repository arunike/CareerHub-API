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


class HolidayCachingTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="holiday-cache-user",
            email="holiday-cache@example.com",
            password="test-pass-123",
        )
        self.client.force_login(self.user)

    def test_holiday_list_caching_and_invalidation(self):
        from django.core.cache import cache
        from availability.models import CustomHoliday
        
        holiday = CustomHoliday.objects.create(
            user=self.user,
            date="2026-12-25",
            description="Christmas",
            holiday_type="company",
        )
        
        response1 = self.client.get('/api/holidays/')
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response1.data), 1)
        
        CustomHoliday.objects.filter(id=holiday.id).update(description="Christmas Updated")
        
        response2 = self.client.get('/api/holidays/')
        self.assertEqual(response2.data[0]['description'], "Christmas")
        
        holiday.description = "Christmas Updated Save"
        holiday.save()
        
        response3 = self.client.get('/api/holidays/')
        self.assertEqual(response3.data[0]['description'], "Christmas Updated Save")

    def test_holiday_federal_caching_and_invalidation(self):
        from datetime import datetime
        from django.core.cache import cache
        from availability.models import CustomHoliday
        
        response1 = self.client.get('/api/holidays/federal/')
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        count_before = len(response1.data)
        
        holiday = CustomHoliday.objects.create(
            user=self.user,
            date=f"{datetime.now().year}-07-04",
            description="Custom July 4th",
            holiday_type="federal",
            group_id="custom-federal-range",
            is_recurring=True,
        )
        second_holiday = CustomHoliday.objects.create(
            user=self.user,
            date=f"{datetime.now().year}-07-05",
            description="Custom July 4th",
            holiday_type="federal",
            group_id="custom-federal-range",
            is_recurring=True,
        )

        response2 = self.client.get('/api/holidays/federal/')
        self.assertEqual(len(response2.data), count_before + 2)
        custom_items = [
            item
            for item in response2.data
            if item.get("id") in {holiday.id, second_holiday.id}
        ]
        self.assertEqual(len(custom_items), 2)
        for custom_item in custom_items:
            self.assertEqual(custom_item["group_id"], "custom-federal-range")
            self.assertTrue(custom_item["is_recurring"])
            self.assertFalse(custom_item["is_locked"])

    def test_observed_holidays_are_excluded_from_personal_list_and_delete_all(self):
        from availability.models import CustomHoliday

        personal_holiday = CustomHoliday.objects.create(
            user=self.user,
            date="2026-08-01",
            description="Personal Day",
            holiday_type="custom",
        )
        observed_holiday = CustomHoliday.objects.create(
            user=self.user,
            date="2026-08-02",
            description="Company Wellness Day",
            holiday_type="federal",
        )

        list_response = self.client.get('/api/holidays/')
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in list_response.data],
            [personal_holiday.id],
        )

        delete_response = self.client.delete('/api/holidays/delete_all/')
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)
        self.assertFalse(CustomHoliday.objects.filter(id=personal_holiday.id).exists())
        self.assertTrue(CustomHoliday.objects.filter(id=observed_holiday.id).exists())

    def test_federal_endpoint_projects_recurring_holiday_range_to_requested_year(self):
        from datetime import datetime
        from availability.models import CustomHoliday

        source_year = datetime.now().year
        target_year = source_year + 1
        group_id = "yearly-company-shutdown"
        recurring_holidays = [
            CustomHoliday.objects.create(
                user=self.user,
                date=f"{source_year}-12-{day}",
                description="Company Shutdown",
                holiday_type="federal",
                group_id=group_id,
                is_recurring=True,
            )
            for day in (28, 29, 30)
        ]
        non_recurring_holiday = CustomHoliday.objects.create(
            user=self.user,
            date=f"{source_year}-08-15",
            description="One-time Company Day",
            holiday_type="federal",
        )

        response = self.client.get(f'/api/holidays/federal/?year={target_year}')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        projected_items = [
            item
            for item in response.data
            if item.get("id") in {holiday.id for holiday in recurring_holidays}
        ]
        self.assertEqual(
            [item["date"] for item in projected_items],
            [
                f"{target_year}-12-28",
                f"{target_year}-12-29",
                f"{target_year}-12-30",
            ],
        )
        self.assertNotIn(
            non_recurring_holiday.id,
            {item.get("id") for item in response.data},
        )
        self.assertTrue(
            all(item["date"].startswith(str(target_year)) for item in response.data)
        )

    def test_federal_endpoint_rejects_invalid_year(self):
        response = self.client.get('/api/holidays/federal/?year=not-a-year')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("year", response.data)

    def test_recurring_custom_holiday_blocks_availability_in_requested_year(self):
        from datetime import date
        from availability.models import CustomHoliday
        from availability.utils import calculate_availability_for_dates

        CustomHoliday.objects.create(
            user=self.user,
            date="2026-08-17",
            description="Yearly Wellness Day",
            holiday_type="custom",
            is_recurring=True,
        )

        availability = calculate_availability_for_dates(
            [date(2027, 8, 17)],
            user=self.user,
        )

        self.assertNotIn("2027-08-17", availability)
