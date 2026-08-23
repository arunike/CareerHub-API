import re
from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import UserSettings
from ..models import Application, ApplicationTimelineEntry, Company, GoogleSheetSyncConfig, GoogleSheetSyncRow, GoogleSheetSyncRun, Offer
from ..services.google_sheets import (
    DEFAULT_APPLICATION_STAGES,
    _is_sync_config_due,
    _ensure_application_timeline_entry,
    _round_tone,
    _upsert_application,
    apply_import_review,
    build_import_review,
    sync_google_sheet,
)

class GoogleSheetSyncStagesTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sheet-status-user@example.com",
            email="sheet-status-user@example.com",
            password="StrongPassw0rd!",
        )

    def test_default_application_stages_use_requested_palette(self):
        self.assertEqual(
            DEFAULT_APPLICATION_STAGES,
            [
                {'key': 'APPLIED', 'label': 'Applied', 'shortLabel': 'Apply', 'tone': '#DCEBFF'},
                {'key': 'ROUND_1', 'label': '1st Round', 'shortLabel': 'R1', 'tone': '#A9CCFF'},
                {'key': 'ROUND_2', 'label': '2nd Round', 'shortLabel': 'R2', 'tone': '#6EA8FE'},
                {'key': 'ROUND_3', 'label': '3rd Round', 'shortLabel': 'R3', 'tone': '#7B8CDE'},
                {'key': 'ROUND_4', 'label': '4th Round', 'shortLabel': 'R4', 'tone': '#9B7EDE'},
                {'key': 'FINAL_ROUND', 'label': 'Final Round', 'shortLabel': 'Final', 'tone': '#6F42C1'},
                {'key': 'ONSITE', 'label': 'Onsite Interview', 'shortLabel': 'Onsite', 'tone': '#20B2AA'},
                {'key': 'OFFER', 'label': 'Offer', 'shortLabel': 'Offer', 'tone': '#34A853'},
                {'key': 'REJECTED', 'label': 'Rejected', 'shortLabel': 'Reject', 'tone': '#E85D5D'},
                {'key': 'GHOSTED', 'label': 'Ghosted', 'shortLabel': 'Ghost', 'tone': '#9AA0A6'},
                {'key': 'REMOVED_FROM_SHEET', 'label': 'Removed', 'shortLabel': 'Removed', 'tone': '#5F6368'},
            ],
        )

    def test_parenthesized_round_status_reuses_existing_round_stage(self):
        UserSettings.objects.create(
            user=self.user,
            application_stages=[
                {'key': 'APPLIED', 'label': 'Applied', 'shortLabel': 'Apply', 'tone': 'bg-blue-500'},
                {'key': 'ROUND_2', 'label': '2nd Round', 'shortLabel': 'R2', 'tone': 'bg-amber-500'},
            ],
        )

        application, _, _ = _upsert_application(
            config=type('Config', (), {'user': self.user})(),
            payload={
                '_user': self.user,
                'company_name': 'Netflix',
                'role_title': 'Software Engineer',
                'status': '2nd round (technical interview)',
            },
            tracked=None,
        )

        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(application.status, 'ROUND_2')
        self.assertEqual(
            sum(1 for stage in settings.application_stages if stage['key'] == 'ROUND_2'),
            1,
        )

    def test_unknown_round_status_adds_timeline_stage(self):
        application, _, _ = _upsert_application(
            config=type('Config', (), {'user': self.user})(),
            payload={
                '_user': self.user,
                'company_name': 'Netflix',
                'role_title': 'Backend Engineer',
                'status': '10th round (bar raiser)',
            },
            tracked=None,
        )

        settings = UserSettings.objects.get(user=self.user)
        stage = next(stage for stage in settings.application_stages if stage['key'] == 'ROUND_10')
        self.assertEqual(application.status, 'ROUND_10')
        self.assertEqual(stage['label'], '10th Round')
        self.assertEqual(stage['shortLabel'], 'R10')
        self.assertEqual(stage['tone'], _round_tone(10))

    def test_extra_round_colors_are_generated_and_distinct(self):
        generated_tones = [_round_tone(round_number) for round_number in range(5, 13)]

        self.assertEqual(len(generated_tones), len(set(generated_tones)))
        self.assertTrue(all(re.fullmatch(r'#[0-9A-F]{6}', tone) for tone in generated_tones))
        self.assertTrue(set(generated_tones).isdisjoint({'#A9CCFF', '#6EA8FE', '#7B8CDE', '#9B7EDE'}))

    def test_extra_round_import_preserves_existing_profile_stages(self):
        existing_stages = [
            {
                'key': 'APPLIED',
                'label': 'My Applied Stage',
                'shortLabel': 'Mine',
                'tone': '#123456',
            }
        ]
        UserSettings.objects.create(user=self.user, application_stages=existing_stages)

        application, _, _ = _upsert_application(
            config=type('Config', (), {'user': self.user})(),
            payload={
                '_user': self.user,
                'company_name': 'Netflix',
                'role_title': 'Platform Engineer',
                'status': '7th round',
            },
            tracked=None,
        )

        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(application.status, 'ROUND_7')
        self.assertEqual(settings.application_stages[0], existing_stages[0])
        self.assertEqual(
            settings.application_stages[1],
            {
                'key': 'ROUND_7',
                'label': '7th Round',
                'shortLabel': 'R7',
                'tone': _round_tone(7),
            },
        )
        self.assertEqual(len(settings.application_stages), 2)

    def test_final_round_import_is_distinct_from_onsite(self):
        application, _, _ = _upsert_application(
            config=type('Config', (), {'user': self.user})(),
            payload={
                '_user': self.user,
                'company_name': 'Netflix',
                'role_title': 'Product Engineer',
                'status': 'Final Round',
            },
            tracked=None,
        )

        settings = UserSettings.objects.get(user=self.user)
        final_stage = next(
            stage for stage in settings.application_stages if stage['key'] == 'FINAL_ROUND'
        )
        self.assertEqual(application.status, 'FINAL_ROUND')
        self.assertEqual(final_stage['tone'], '#6F42C1')
