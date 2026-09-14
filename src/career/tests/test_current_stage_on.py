from datetime import date

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from career.models import Application, ApplicationTimelineEntry, Company


class CurrentStageOnTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='san.zhang', email='rounds@example.com', password='StrongPassw0rd!'
        )
        self.client.force_authenticate(self.user)
        self.company = Company.objects.create(name='Google')
        self.application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title='Software Engineer',
            status='ROUND_2',
        )

    def _entry(self, stage, event_date, **extra):
        return ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=self.application,
            stage=stage,
            event_date=event_date,
            **extra,
        )

    def _fetch(self):
        response = self.client.get(f'/api/career/applications/{self.application.id}/')
        self.assertEqual(response.status_code, 200)
        return response.data['current_stage_on']

    def test_reports_the_date_the_current_stage_was_reached(self):
        self._entry('ROUND_1', date(2026, 7, 1))
        self._entry('ROUND_2', date(2026, 10, 1))
        self.assertEqual(self._fetch(), '2026-10-01')

    def test_ignores_stages_the_application_has_moved_past(self):
        self._entry('ROUND_1', date(2026, 10, 1))
        self.assertIsNone(self._fetch())

    def test_a_stage_cannot_be_recorded_twice_for_one_application(self):
        from django.db import IntegrityError, transaction

        self._entry('ROUND_2', date(2026, 7, 1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._entry('ROUND_2', date(2026, 11, 1))

    def test_ignores_an_entry_the_user_deleted(self):
        from django.utils import timezone

        self._entry('ROUND_2', date(2026, 10, 1), deleted_by_user_at=timezone.now())
        self.assertIsNone(self._fetch())

    def test_ignores_an_undated_entry(self):
        self._entry('ROUND_2', None)
        self.assertIsNone(self._fetch())

    def test_is_null_with_no_timeline_at_all(self):
        self.assertIsNone(self._fetch())
