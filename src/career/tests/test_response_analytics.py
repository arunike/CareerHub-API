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


class ResponseTrendTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="response-trend@example.com",
            email="response-trend@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.today = timezone.localdate()
        self.company = Company.objects.create(user=self.user, name='Google')

    def _app(self, applied, responded, *, applied_entry=None):
        application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title='Software Engineer',
            status='SCREEN' if responded else 'APPLIED',
            date_applied=applied,
        )
        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='APPLIED',
            event_date=applied_entry or applied,
        )
        if responded:
            ApplicationTimelineEntry.objects.create(
                user=self.user,
                application=application,
                stage='SCREEN',
                event_date=applied + timedelta(days=3),
            )
        return application

    def _seed(self, days_ago, count, responded_count, **kwargs):
        for index in range(count):
            self._app(self.today - timedelta(days=days_ago), index < responded_count, **kwargs)

    def test_trend_compares_cohorts_that_have_had_equal_time_to_reply(self):
        """A fresh batch that has not answered yet must not read as a collapse."""
        # p90 will be 3 days, since every reply lands on day 3.
        self._seed(40, 20, 10)  # older window: 50%
        self._seed(10, 20, 5)  # recent window: 25%
        self._seed(1, 40, 0)  # applied yesterday, no chance to reply yet

        data = self.client.get('/api/career/application-timeline-analytics/').json()
        trend = data['response_trend']
        self.assertIsNotNone(trend)
        self.assertEqual(trend['recent']['applied'], 20)
        self.assertEqual(trend['previous']['applied'], 20)
        self.assertEqual(trend['recent']['response_rate'], 25.0)
        self.assertEqual(trend['previous']['response_rate'], 50.0)
        self.assertEqual(trend['delta'], -25.0)
        # The 40 unanswerable applications from yesterday are in neither cohort.
        self.assertNotIn(40, [trend['recent']['applied'], trend['previous']['applied']])

    def test_trend_cohorts_use_date_applied_not_the_synced_timeline_entry(self):
        """Cohort membership must key off the date the user recorded."""
        # Only the older batch replies, so the p90 that sets the windows comes from rows whose
        # dates agree — the drift under test cannot move the windows themselves.
        self._seed(50, 20, 10)
        self._seed(10, 20, 0, applied_entry=self.today - timedelta(days=50))

        trend = self.client.get('/api/career/application-timeline-analytics/').json()[
            'response_trend'
        ]
        self.assertIsNotNone(trend, 'the recent cohort was swallowed by the drifted entry date')
        self.assertEqual(trend['recent']['applied'], 20)
        self.assertEqual(trend['previous']['applied'], 20)
        self.assertEqual(trend['recent']['response_rate'], 0.0)
        self.assertEqual(trend['previous']['response_rate'], 50.0)
        self.assertEqual(trend['delta'], -50.0)

    def test_trend_is_withheld_when_a_cohort_is_too_small_to_mean_anything(self):
        self._seed(40, 3, 1)
        self._seed(10, 3, 2)
        self.assertIsNone(
            self.client.get('/api/career/application-timeline-analytics/').json()['response_trend']
        )


class InterviewLinkTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="interview-links@example.com",
            email="interview-links@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.today = timezone.localdate()

    def test_reports_how_much_of_the_calendar_is_linked(self):
        company = Company.objects.create(user=self.user, name='Google')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='OFFER',
            date_applied=self.today,
        )
        for index in range(3):
            Event.objects.create(
                user=self.user,
                name=f'Interview {index}',
                date=self.today,
                start_time=time(10, 0),
                end_time=time(11, 0),
                application=application if index < 2 else None,
            )

        links = self.client.get('/api/career/application-timeline-analytics/').json()[
            'interview_links'
        ]
        self.assertEqual(links['total_events'], 3)
        self.assertEqual(links['linked_events'], 2)
        self.assertEqual(links['unlinked_events'], 1)
        self.assertEqual(links['interviews_per_offer'], 2.0)

    def test_interviews_per_offer_is_null_while_nothing_is_linked(self):
        Event.objects.create(
            user=self.user,
            name='Interview',
            date=self.today,
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        links = self.client.get('/api/career/application-timeline-analytics/').json()[
            'interview_links'
        ]
        self.assertEqual(links['unlinked_events'], 1)
        # Unanswerable until something is linked, so it is null rather than 0.
        self.assertIsNone(links['interviews_per_offer'])


class FieldCompletenessTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="field-completeness@example.com",
            email="field-completeness@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_blank_fields_are_reported_worst_first_with_what_they_unlock(self):
        company = Company.objects.create(user=self.user, name='Google')
        for index in range(4):
            Application.objects.create(
                user=self.user,
                company=company,
                role_title='Software Engineer',
                status='APPLIED',
                date_applied=timezone.localdate(),
                # Level filled on one row only; salary_range on three.
                level='L4' if index == 0 else '',
                salary_range='' if index == 0 else '100000 - 150000',
            )

        rows = self.client.get('/api/career/application-stats/').json()['field_completeness']
        by_field = {row['field']: row for row in rows}
        self.assertEqual(by_field['level']['missing'], 3)
        self.assertEqual(by_field['level']['total'], 4)
        self.assertEqual(by_field['salary_range']['missing'], 1)
        self.assertTrue(by_field['level']['unlocks'])
        # Worst first, so the biggest win is at the top of the list.
        self.assertEqual([row['missing'] for row in rows], sorted((r['missing'] for r in rows), reverse=True))

    def test_fields_that_are_fully_populated_are_not_reported(self):
        company = Company.objects.create(user=self.user, name='Google')
        Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='APPLIED',
            date_applied=timezone.localdate(),
            level='L4',
            office_location='New York, NY',
            salary_range='100000 - 150000',
            job_link='https://example.com/job',
            job_description='Build things.',
        )
        self.assertEqual(
            self.client.get('/api/career/application-stats/').json()['field_completeness'], []
        )
