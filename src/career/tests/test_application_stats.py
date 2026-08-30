import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import Event, UserSettings
from ..models import Application, ApplicationTimelineEntry, Company, GoogleSheetSyncConfig, GoogleSheetSyncRow, Offer
from ..services.timeline_analytics import build_application_timeline_analytics


class ApplicationStatsAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="application-stats-user@example.com",
            email="application-stats-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.today = timezone.localdate()

    def _application(self, status_value, *, applied=None, location='', office='', round_no=0):
        company, _ = Company.objects.get_or_create(user=self.user, name='Google')
        return Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status=status_value,
            date_applied=applied,
            location=location,
            office_location=office,
            current_round=round_no,
        )

    def test_counts_match_the_definitions_the_dashboard_uses(self):
        self._application('APPLIED', applied=self.today)
        self._application('SCREEN', applied=self.today)
        self._application('OFFER', applied=self.today)
        self._application('ACCEPTED', applied=self.today)
        self._application('OFFER_REJECTED', applied=self.today)
        self._application('GHOSTED', applied=self.today)
        # A rejection only counts as an interview when a round was actually reached.
        self._application('REJECTED', applied=self.today, round_no=0)
        self._application('REJECTED', applied=self.today, round_no=2)

        response = self.client.get('/api/career/application-stats/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['total'], 8)
        # OFFER, ACCEPTED and OFFER_REJECTED all count as an offer having been made.
        self.assertEqual(data['offers'], 3)
        self.assertEqual(data['ghosted'], 1)
        # Everything except APPLIED, REJECTED, GHOSTED, ACCEPTED and REMOVED_FROM_SHEET.
        self.assertEqual(data['active_interviews'], 3)
        # SCREEN, OFFER, ACCEPTED, OFFER_REJECTED, and only the rejection with a round.
        self.assertEqual(data['total_interviews'], 5)
        # Everything except APPLIED, GHOSTED and REMOVED_FROM_SHEET.
        self.assertEqual(data['responded_count'], 6)
        self.assertEqual(data['response_rate'], '75.0')
        self.assertEqual(data['offer_rate'], '37.5')

    def test_locations_group_to_city_and_collapse_remote(self):
        self._application('APPLIED', applied=self.today, office='New York, NY')
        self._application('APPLIED', applied=self.today, office='New York, NY')
        self._application('APPLIED', applied=self.today, location='Remote - US')
        self._application('APPLIED', applied=self.today, location='fully remote')
        self._application('APPLIED', applied=self.today)

        data = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(
            {row['name']: row['count'] for row in data['locations']},
            {'New York': 2, 'Remote': 2, 'Unknown': 1},
        )
        # Sorted by count, so the dashboard's "top locations" list needs no client sort.
        self.assertGreaterEqual(data['locations'][0]['count'], data['locations'][-1]['count'])

    def test_age_buckets_and_recent_window(self):
        self._application('APPLIED', applied=self.today)
        self._application('APPLIED', applied=self.today - timedelta(days=20))
        self._application('APPLIED', applied=self.today - timedelta(days=60))
        self._application('APPLIED', applied=self.today - timedelta(days=200))
        # Age falls back to created_at when there is no applied date.
        self._application('APPLIED', applied=None)

        data = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(
            {row['name']: row['count'] for row in data['application_age_breakdown']},
            {'Last 7 days': 2, '8-30 days': 1, '31-90 days': 1, '90+ days': 1},
        )
        # Today, 20 days ago, and the created-today fallback; 30 days old is already outside.
        self.assertEqual(data['recent_applications_30d'], 3)

    def test_thirty_day_window_excludes_the_boundary_day(self):
        self._application('APPLIED', applied=self.today - timedelta(days=29))
        self._application('APPLIED', applied=self.today - timedelta(days=30))

        data = self.client.get('/api/career/application-stats/').json()
        # A date exactly 30 days old falls outside the window.
        self.assertEqual(data['recent_applications_30d'], 1)

    def test_daily_histogram_replaces_the_application_list(self):
        self._application('APPLIED', applied=self.today)
        self._application('APPLIED', applied=self.today)
        self._application('APPLIED', applied=self.today - timedelta(days=1))
        self._application('APPLIED', applied=None)

        data = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(
            data['daily_applied'],
            {
                (self.today - timedelta(days=1)).isoformat(): 1,
                self.today.isoformat(): 2,
            },
        )
        # Undated rows cannot be placed on the chart, so they are left out of the histogram.
        self.assertEqual(sum(data['daily_applied'].values()), 3)

    def test_year_filter_narrows_counts_but_never_the_year_list(self):
        self._application('APPLIED', applied=date(2024, 5, 1))
        self._application('APPLIED', applied=date(2026, 5, 1))
        self._application('APPLIED', applied=date(2026, 6, 1))

        unfiltered = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(unfiltered['total'], 3)
        self.assertEqual(unfiltered['years'], [2026, 2024])

        filtered = self.client.get('/api/career/application-stats/?year=2026').json()
        self.assertEqual(filtered['total'], 2)
        # The picker must keep every year, or selecting one would strand the user on it.
        self.assertEqual(filtered['years'], [2026, 2024])

        for value in ('all', 'garbage', ''):
            with self.subTest(year=value):
                self.assertEqual(
                    self.client.get(f'/api/career/application-stats/?year={value}').json()['total'],
                    3,
                )

    def test_stats_are_scoped_to_the_requesting_user(self):
        other = get_user_model().objects.create_user(
            username="other-stats-user@example.com",
            email="other-stats-user@example.com",
            password="StrongPassw0rd!",
        )
        other_company = Company.objects.create(user=other, name='Netflix')
        Application.objects.create(
            user=other,
            company=other_company,
            role_title='Software Engineer',
            status='OFFER',
            date_applied=self.today,
        )
        self._application('APPLIED', applied=self.today)

        data = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['offers'], 0)

    def test_stats_require_authentication(self):
        self.client.force_authenticate(None)
        response = self.client.get('/api/career/application-stats/')
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
