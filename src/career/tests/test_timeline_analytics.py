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


class ApplicationTimelineAnalyticsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="timeline-analytics-user@example.com",
            email="timeline-analytics-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        UserSettings.objects.create(
            user=self.user,
            ghosting_threshold_days=10,
            application_stages=[
                {'key': 'APPLIED', 'label': 'Applied', 'shortLabel': 'Apply', 'tone': 'bg-blue-500'},
                {'key': 'SCREEN', 'label': 'Phone Screen', 'shortLabel': 'Screen', 'tone': 'bg-sky-500'},
                {'key': 'OFFER', 'label': 'Offer', 'shortLabel': 'Offer', 'tone': 'bg-emerald-500'},
            ],
        )

    def test_timeline_analytics_connects_timeline_and_sheet_source(self):
        company = Company.objects.create(user=self.user, name='Plaid')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='OFFER',
            date_applied='2026-04-01',
            salary_range='148800 - 223200',
            location='New York, NY',
        )
        offer = Offer.objects.create(
            application=application,
            base_salary=150000,
        )
        offer.created_at = timezone.make_aware(datetime(2026, 4, 11, 12, 0))
        offer.save()

        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='APPLIED',
            event_date='2026-04-01',
        )
        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='SCREEN',
            event_date='2026-04-06',
        )
        config = GoogleSheetSyncConfig.objects.create(
            user=self.user,
            name='Job Applications',
            sheet_url='https://docs.google.com/spreadsheets/d/test/edit',
            spreadsheet_id='test',
            target_type=GoogleSheetSyncConfig.TARGET_APPLICATIONS,
            column_mapping={},
        )
        GoogleSheetSyncRow.objects.create(
            config=config,
            external_key='plaid-software-engineer',
            row_number=2,
            row_hash='abc',
            local_object_type='career.Application',
            local_object_id=application.id,
        )

        # Create a manual application with an offer, which should be excluded from sheet sources
        Application.objects.create(
            user=self.user,
            company=company,
            role_title='Manual Engineer',
            status='OFFER',
            date_applied='2026-04-01',
        )

        analytics = build_application_timeline_analytics(self.user)

        self.assertEqual(analytics['average_time_to_interview_days'], 5)
        self.assertEqual(analytics['time_to_interview_sample_size'], 1)
        self.assertEqual(analytics['average_days_to_offer'], 10)
        self.assertEqual(analytics['days_to_offer_sample_size'], 1)
        screen_stage = next(stage for stage in analytics['stage_conversion'] if stage['key'] == 'SCREEN')
        self.assertEqual(screen_stage['reached_count'], 2)
        self.assertEqual(screen_stage['conversion_rate'], 1.0)  # Both applications reached screen (one directly, one via OFFER backfill)
        self.assertEqual(len(analytics['offer_rate_by_source']), 1)
        self.assertEqual(analytics['offer_rate_by_source'][0]['name'], 'Job Applications')
        self.assertEqual(analytics['offer_rate_by_source'][0]['offers'], 1)

        response = self.client.get('/api/career/application-timeline-analytics/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['average_time_to_interview_days'], 5)
        self.assertEqual(response.data['average_days_to_offer'], 10)

    def test_stale_in_stage_uses_settings_threshold(self):
        company = Company.objects.create(user=self.user, name='Google')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            status='SCREEN',
            date_applied='2026-03-01',
        )
        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='SCREEN',
            event_date='2026-03-15',
        )

        analytics = build_application_timeline_analytics(self.user)

        self.assertEqual(analytics['stale_threshold_days'], 10)
        self.assertEqual(analytics['stale_in_stage'][0]['application_id'], application.id)


class FunnelConversionPrecisionTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="funnel-precision@example.com",
            email="funnel-precision@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_rare_stage_keeps_enough_precision_to_avoid_reading_as_zero(self):
        """A real count must never be reportable as 0%."""
        company = Company.objects.create(user=self.user, name='Google')
        applied = timezone.localdate()
        for index in range(806):
            application = Application.objects.create(
                user=self.user,
                company=company,
                role_title=f'Engineer {index}',
                status='OFFER' if index < 2 else 'APPLIED',
                date_applied=applied,
            )
            ApplicationTimelineEntry.objects.create(
                user=self.user,
                application=application,
                stage=application.status,
                event_date=applied,
            )

        data = self.client.get('/api/career/application-timeline-analytics/').json()
        offer = next(row for row in data['stage_conversion'] if row['key'] == 'OFFER')
        self.assertEqual(offer['reached_count'], 2)
        # Enough precision that a one-decimal percentage is non-zero and accurate.
        self.assertAlmostEqual(offer['conversion_rate'], 2 / 806, places=6)
        self.assertGreaterEqual(round(offer['conversion_rate'] * 100, 1), 0.2)


class TimelineAnalyticsInsightTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="timeline-insight@example.com",
            email="timeline-insight@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        UserSettings.objects.create(user=self.user, ghosting_threshold_days=30)
        self.today = timezone.localdate()

    def _app(self, name, status, applied, entries=(), level='', location=''):
        company, _ = Company.objects.get_or_create(user=self.user, name=name)
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status=status,
            date_applied=applied,
            level=level,
            office_location=location,
        )
        for stage, event_date in entries:
            ApplicationTimelineEntry.objects.create(
                user=self.user, application=application, stage=stage, event_date=event_date
            )
        return application

    def _analytics(self):
        return self.client.get('/api/career/application-timeline-analytics/').json()

    def test_days_to_offer_uses_the_offer_date_not_when_the_record_was_typed_in(self):
        applied = self.today - timedelta(days=400)
        offer_arrived = applied + timedelta(days=30)
        application = self._app(
            'Google', 'ACCEPTED', applied,
            entries=[('APPLIED', applied), ('OFFER', offer_arrived)],
        )
        # Backfilled today, long after the offer actually arrived.
        Offer.objects.create(application=application, base_salary=Decimal('100000'))

        data = self._analytics()
        # 30, from the timeline — not ~400, which is when the Offer row was created.
        self.assertEqual(data['average_days_to_offer'], 30)
        self.assertEqual(data['days_to_offer_sample_size'], 1)

    def test_days_to_offer_falls_back_to_the_record_when_no_timeline_entry_exists(self):
        applied = self.today - timedelta(days=10)
        application = self._app('Netflix', 'OFFER', applied, entries=[('APPLIED', applied)])
        Offer.objects.create(application=application, base_salary=Decimal('100000'))

        data = self._analytics()
        # No OFFER entry to read, so the record's creation date is all there is: 10 days.
        self.assertEqual(data['average_days_to_offer'], 10)

    def test_reply_timing_buckets_and_followup_cutoff(self):
        # Replies at 2, 5, 20 and 45 days, plus one that never answered.
        for index, delay in enumerate([2, 5, 20, 45]):
            applied = self.today - timedelta(days=90)
            self._app(
                f'Company {index}', 'SCREEN', applied,
                entries=[('APPLIED', applied), ('SCREEN', applied + timedelta(days=delay))],
            )
        silent_applied = self.today - timedelta(days=70)
        self._app('Silent', 'APPLIED', silent_applied, entries=[('APPLIED', silent_applied)])

        data = self._analytics()
        self.assertEqual(data['response_time_sample_size'], 4)
        buckets = {row['label']: row['count'] for row in data['response_time_buckets']}
        self.assertEqual(buckets['0-7 days'], 2)
        self.assertEqual(buckets['15-30 days'], 1)
        self.assertEqual(buckets['31-60 days'], 1)
        # Cumulative share is monotonic and ends at everything.
        shares = [row['cumulative_share'] for row in data['response_time_buckets']]
        self.assertEqual(shares, sorted(shares))
        self.assertEqual(shares[-1], 1)
        # p90 of [2, 5, 20, 45] by nearest rank is 45, not a bucket edge.
        self.assertEqual(data['p90_days_to_response'], 45)
        self.assertEqual(data['suggested_followup_days'], 45)
        # The silent one has waited 70 days, past that cutoff.
        self.assertEqual(data['open_without_response_count'], 1)
        self.assertEqual(data['silent_past_followup_count'], 1)

    def test_response_segments_report_rate_with_sample_size(self):
        applied = self.today - timedelta(days=60)
        # Palo Alto: 1 of 2 replied. Remote: 0 of 1.
        self._app('A', 'SCREEN', applied, entries=[('APPLIED', applied), ('SCREEN', applied)], location='Palo Alto, CA')
        self._app('B', 'APPLIED', applied, entries=[('APPLIED', applied)], location='Palo Alto, CA')
        self._app('C', 'APPLIED', applied, entries=[('APPLIED', applied)], location='Remote - US')

        rows = {row['name']: row for row in self._analytics()['response_rate_by_location']}
        self.assertEqual(rows['Palo Alto']['total'], 2)
        self.assertEqual(rows['Palo Alto']['responded'], 1)
        self.assertAlmostEqual(rows['Palo Alto']['response_rate'], 0.5)
        self.assertEqual(rows['Remote']['responded'], 0)
        # The sample size travels with the rate so a caller can refuse to show n=1.
        self.assertEqual(rows['Remote']['total'], 1)

    def test_rejected_after_interviewing_still_counts_as_a_response(self):
        applied = self.today - timedelta(days=60)
        self._app(
            'Rejector', 'REJECTED', applied,
            entries=[('APPLIED', applied), ('SCREEN', applied + timedelta(days=3)), ('REJECTED', applied + timedelta(days=9))],
        )
        data = self._analytics()
        # Status alone says rejected; the timeline says they replied in 3 days.
        self.assertEqual(data['response_time_sample_size'], 1)
        self.assertEqual(data['median_days_to_response'], 3)

    def test_stage_durations_and_per_stage_staleness_context(self):
        # Three applications each took 10 days from 1st to 2nd round.
        for index in range(3):
            applied = self.today - timedelta(days=120)
            self._app(
                f'Mover {index}', 'REJECTED', applied,
                entries=[
                    ('APPLIED', applied),
                    ('ROUND_1', applied + timedelta(days=5)),
                    ('ROUND_2', applied + timedelta(days=15)),
                ],
            )
        # One still sitting in 1st round, 100 days in.
        stuck_applied = self.today - timedelta(days=100)
        self._app('Stuck', 'ROUND_1', stuck_applied, entries=[('APPLIED', stuck_applied), ('ROUND_1', stuck_applied)])

        data = self._analytics()
        durations = {row['key']: row for row in data['stage_durations']}
        self.assertEqual(durations['ROUND_1']['median_days'], 10)
        self.assertEqual(durations['ROUND_1']['sample_size'], 3)

        stuck = next(row for row in data['stale_in_stage'] if row['company'] == 'Stuck')
        self.assertEqual(stuck['days_in_stage'], 100)
        self.assertEqual(stuck['typical_days'], 10)
        self.assertEqual(stuck['days_over_typical'], 90)

    def test_a_single_transition_is_not_treated_as_a_typical_duration(self):
        applied = self.today - timedelta(days=120)
        self._app(
            'Lonely', 'REJECTED', applied,
            entries=[('APPLIED', applied), ('ROUND_3', applied + timedelta(days=1)), ('ROUND_4', applied + timedelta(days=60))],
        )
        stuck_applied = self.today - timedelta(days=90)
        self._app('Stuck', 'ROUND_3', stuck_applied, entries=[('APPLIED', stuck_applied), ('ROUND_3', stuck_applied)])

        data = self._analytics()
        durations = {row['key']: row for row in data['stage_durations']}
        # Reported with its sample size...
        self.assertEqual(durations['ROUND_3']['sample_size'], 1)
        self.assertLess(durations['ROUND_3']['sample_size'], data['min_duration_sample'])
        # ...but not used as a comparison, so nothing is flagged against an anecdote.
        stuck = next(row for row in data['stale_in_stage'] if row['company'] == 'Stuck')
        self.assertIsNone(stuck['typical_days'])
        self.assertIsNone(stuck['days_over_typical'])
