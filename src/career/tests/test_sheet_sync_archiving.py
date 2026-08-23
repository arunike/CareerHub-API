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

class GoogleSheetSyncArchivingTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sheet-status-user@example.com",
            email="sheet-status-user@example.com",
            password="StrongPassw0rd!",
        )

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_missing_external_id_row_archives_then_deletes_application(self, mock_fetch_sheet_rows):
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['google-swe', 'Google', 'Software Engineer', '1st Round'],
            ['stripe-be', 'Stripe', 'Backend Engineer', 'Applied'],
        ]
        config = GoogleSheetSyncConfig.objects.create(
            user=self.user,
            name='Applications',
            sheet_url='https://docs.google.com/spreadsheets/d/test/edit',
            spreadsheet_id='test',
            target_type=GoogleSheetSyncConfig.TARGET_APPLICATIONS,
            column_mapping={
                'external_id': 'External ID',
                'company_name': 'Company',
                'role_title': 'Role',
                'status': 'Status',
            },
            missing_row_delete_after_days=30,
        )
        sync_google_sheet(config)

        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['stripe-be', 'Stripe', 'Backend Engineer', 'Applied'],
        ]
        archived_result = sync_google_sheet(config)

        google_app = Application.objects.get(user=self.user, company__name='Google')
        self.assertEqual(archived_result['archived'], 1)
        self.assertEqual(archived_result['deleted'], 0)
        self.assertEqual(google_app.status, 'REMOVED_FROM_SHEET')
        self.assertEqual(google_app.source_removed_previous_status, 'ROUND_1')
        self.assertIsNotNone(google_app.source_removed_at)
        self.assertTrue(any(entry['type'] == 'source_archived' for entry in archived_result['history']))

        google_app.source_removed_delete_after = timezone.now() - timedelta(days=1)
        google_app.save(update_fields=['source_removed_delete_after'])
        deleted_result = sync_google_sheet(config)

        self.assertEqual(deleted_result['deleted'], 1)
        self.assertFalse(Application.objects.filter(user=self.user, company__name='Google').exists())
        self.assertFalse(GoogleSheetSyncRow.objects.filter(config=config, external_key='google-swe').exists())

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_missing_identity_rows_without_external_id_mapping_are_archived(self, mock_fetch_sheet_rows):
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role'],
            ['Google', 'Software Engineer'],
            ['Stripe', 'Backend Engineer'],
        ]
        config = GoogleSheetSyncConfig.objects.create(
            user=self.user,
            name='Applications',
            sheet_url='https://docs.google.com/spreadsheets/d/test/edit',
            spreadsheet_id='test',
            target_type=GoogleSheetSyncConfig.TARGET_APPLICATIONS,
            column_mapping={
                'company_name': 'Company',
                'role_title': 'Role',
            },
        )
        sync_google_sheet(config)

        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role'],
            ['Stripe', 'Backend Engineer'],
        ]
        result = sync_google_sheet(config)

        google_app = Application.objects.get(user=self.user, company__name='Google')
        self.assertEqual(result['archived'], 1)
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(result['missing_from_sheet'], 1)
        self.assertFalse(result['warnings'])
        self.assertEqual(google_app.status, 'REMOVED_FROM_SHEET')
        self.assertIsNotNone(google_app.source_removed_at)

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_missing_row_number_fallback_rows_are_not_archived(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Google')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='APPLIED',
        )
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role'],
            ['Stripe', 'Backend Engineer'],
        ]
        config = GoogleSheetSyncConfig.objects.create(
            user=self.user,
            name='Applications',
            sheet_url='https://docs.google.com/spreadsheets/d/test/edit',
            spreadsheet_id='test',
            target_type=GoogleSheetSyncConfig.TARGET_APPLICATIONS,
            column_mapping={
                'company_name': 'Company',
                'role_title': 'Role',
            },
        )
        GoogleSheetSyncRow.objects.create(
            config=config,
            external_key='row:2',
            row_number=2,
            row_hash='legacy-row-number',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        result = sync_google_sheet(config)

        self.assertEqual(result['archived'], 0)
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(result['missing_from_sheet'], 0)
        application.refresh_from_db()
        self.assertEqual(application.status, 'APPLIED')

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_reappearing_external_id_restores_archived_application(self, mock_fetch_sheet_rows):
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['google-swe', 'Google', 'Software Engineer', '1st Round'],
        ]
        config = GoogleSheetSyncConfig.objects.create(
            user=self.user,
            name='Applications',
            sheet_url='https://docs.google.com/spreadsheets/d/test/edit',
            spreadsheet_id='test',
            target_type=GoogleSheetSyncConfig.TARGET_APPLICATIONS,
            column_mapping={
                'external_id': 'External ID',
                'company_name': 'Company',
                'role_title': 'Role',
                'status': 'Status',
            },
        )
        sync_google_sheet(config)
        mock_fetch_sheet_rows.return_value = [['External ID', 'Company', 'Role', 'Status']]
        sync_google_sheet(config)

        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['google-swe', 'Google', 'Software Engineer', '1st Round'],
        ]
        result = sync_google_sheet(config)

        application = Application.objects.get(user=self.user, company__name='Google')
        self.assertEqual(result['updated'], 1)
        self.assertEqual(application.status, 'ROUND_1')
        self.assertIsNone(application.source_removed_at)
        self.assertEqual(application.source_removed_previous_status, '')
