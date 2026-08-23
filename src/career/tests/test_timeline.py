import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import UserSettings
from ..models import Application, ApplicationTimelineEntry, Company, Offer, application_timeline_stage_order
from ..services.google_sheets import _ensure_application_timeline_entry


class ApplicationTimelineEntryModelTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="timeline-entry-user@example.com",
            email="timeline-entry-user@example.com",
            password="StrongPassw0rd!",
        )
        self.company = Company.objects.create(user=self.user, name='Google')
        self.application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title='Backend Engineer',
        )

    def test_user_date_override_is_not_refilled_by_sync(self):
        entry = ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=self.application,
            stage='ROUND_1',
            event_date=None,
            event_date_is_user_override=True,
        )

        _ensure_application_timeline_entry(self.application, 'ROUND_1', '2026-07-18')

        entry.refresh_from_db()
        self.assertIsNone(entry.event_date)

    def test_round_stage_order_uses_round_number_not_settings_position(self):
        UserSettings.objects.create(
            user=self.user,
            application_stages=[
                {'key': 'APPLIED', 'label': 'Applied', 'shortLabel': 'Apply', 'tone': 'bg-blue-500'},
                {'key': 'ROUND_1', 'label': '1st Round', 'shortLabel': 'R1', 'tone': 'bg-amber-400'},
                {'key': 'ROUND_3', 'label': '3rd Round', 'shortLabel': 'R3', 'tone': 'bg-orange-500'},
                {'key': 'ROUND_2', 'label': '2nd Round', 'shortLabel': 'R2', 'tone': 'bg-amber-500'},
            ],
        )

        round_three = ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=self.application,
            stage='ROUND_3',
        )
        round_two = ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=self.application,
            stage='ROUND_2',
        )

        self.assertEqual(application_timeline_stage_order('ROUND_1'), 30)
        self.assertEqual(application_timeline_stage_order('ROUND_2'), 40)
        self.assertEqual(application_timeline_stage_order('ROUND_3'), 50)
        self.assertEqual(round_two.stage_order, 40)
        self.assertEqual(round_three.stage_order, 50)
        self.assertEqual(
            list(
                ApplicationTimelineEntry.objects.filter(application=self.application)
                .order_by('stage_order')
                .values_list('stage', flat=True)
            ),
            ['ROUND_2', 'ROUND_3'],
        )

    def test_canonical_stage_order_ignores_profile_position(self):
        UserSettings.objects.create(
            user=self.user,
            application_stages=[
                {'key': 'APPLIED', 'label': 'Applied', 'shortLabel': 'Apply', 'tone': '#DCEBFF'},
                {'key': 'OFFER', 'label': 'Offer', 'shortLabel': 'Offer', 'tone': '#34A853'},
                {
                    'key': 'FINAL_ROUND',
                    'label': 'Final Round',
                    'shortLabel': 'Final',
                    'tone': '#6F42C1',
                },
            ],
        )

        offer = ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=self.application,
            stage='OFFER',
            event_date='2026-07-15',
        )
        final_round = ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=self.application,
            stage='FINAL_ROUND',
            event_date='2026-07-08',
        )

        self.assertEqual(final_round.stage_order, 890)
        self.assertEqual(offer.stage_order, 1000)
        self.assertEqual(
            list(
                ApplicationTimelineEntry.objects.filter(application=self.application)
                .order_by('stage_order', 'event_date')
                .values_list('stage', flat=True)
            ),
            ['FINAL_ROUND', 'OFFER'],
        )


class ApplicationTimelineEntryAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='timeline-api-user@example.com',
            email='timeline-api-user@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_authenticate(self.user)
        company = Company.objects.create(user=self.user, name='Google')
        self.application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            status='ROUND_2',
        )
        self.entry = ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=self.application,
            stage='ROUND_2',
            event_date='2026-07-17',
            notes='Technical interview',
        )

    def test_patch_updates_display_title_and_protects_changed_fields(self):
        response = self.client.patch(
            f'/api/career/application-timeline/{self.entry.id}/',
            {
                'display_title': 'Architecture Interview',
                'event_date': None,
                'notes': 'System design and API discussion',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.stage, 'ROUND_2')
        self.assertEqual(self.entry.display_title, 'Architecture Interview')
        self.assertIsNone(self.entry.event_date)
        self.assertTrue(self.entry.event_date_is_user_override)
        self.assertTrue(self.entry.notes_is_user_override)

        stage_response = self.client.patch(
            f'/api/career/application-timeline/{self.entry.id}/',
            {'stage': 'ROUND_3'},
            format='json',
        )
        self.assertEqual(stage_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.stage, 'ROUND_2')

    def test_delete_suppresses_sync_repair_and_manual_create_revives_entry(self):
        delete_response = self.client.delete(
            f'/api/career/application-timeline/{self.entry.id}/'
        )

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.entry.refresh_from_db()
        self.assertIsNotNone(self.entry.deleted_by_user_at)

        _ensure_application_timeline_entry(self.application, 'ROUND_2', '2026-07-18')
        self.entry.refresh_from_db()
        self.assertIsNotNone(self.entry.deleted_by_user_at)
        self.assertEqual(self.entry.event_date.isoformat(), '2026-07-17')

        list_response = self.client.get(
            f'/api/career/application-timeline/?application={self.application.id}'
        )
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data, [])

        create_response = self.client.post(
            '/api/career/application-timeline/',
            {
                'application': self.application.id,
                'stage': 'ROUND_2',
                'display_title': 'Re-added interview',
                'event_date': '2026-07-19',
                'notes': 'Restored manually',
            },
            format='json',
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data['id'], self.entry.id)
        self.entry.refresh_from_db()
        self.assertIsNone(self.entry.deleted_by_user_at)
        self.assertEqual(self.entry.display_title, 'Re-added interview')
