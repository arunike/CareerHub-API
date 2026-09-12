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


class SheetSyncNeverDeletesLocalOnlyDataTests(APITestCase):
    """A row leaving the sheet must not destroy compensation the sheet never held."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sheet-offer-guard@example.com",
            email="sheet-offer-guard@example.com",
            password="StrongPassw0rd!",
        )

    def _config(self):
        return GoogleSheetSyncConfig.objects.create(
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
            missing_row_delete_after_days=5,
        )

    def _both_rows(self):
        return [
            ['External ID', 'Company', 'Role', 'Status'],
            ['google-swe', 'Google', 'Software Engineer', 'Offer'],
            ['stripe-be', 'Stripe', 'Backend Engineer', 'Applied'],
        ]

    def _only_stripe(self):
        return [
            ['External ID', 'Company', 'Role', 'Status'],
            ['stripe-be', 'Stripe', 'Backend Engineer', 'Applied'],
        ]

    def _run_to_deletion(self, mock_fetch_sheet_rows, config):
        mock_fetch_sheet_rows.return_value = self._both_rows()
        sync_google_sheet(config)
        application = Application.objects.get(user=self.user, company__name='Google')

        mock_fetch_sheet_rows.return_value = self._only_stripe()
        sync_google_sheet(config)
        application.refresh_from_db()
        application.source_removed_delete_after = timezone.now() - timedelta(days=1)
        application.save(update_fields=['source_removed_delete_after'])
        return application, sync_google_sheet(config)

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_keeps_an_application_that_carries_an_offer(self, mock_fetch_sheet_rows):
        config = self._config()
        mock_fetch_sheet_rows.return_value = self._both_rows()
        sync_google_sheet(config)
        application = Application.objects.get(user=self.user, company__name='Google')
        Offer.objects.create(application=application, base_salary=165000, bonus=24750)

        mock_fetch_sheet_rows.return_value = self._only_stripe()
        sync_google_sheet(config)
        application.refresh_from_db()
        application.source_removed_delete_after = timezone.now() - timedelta(days=1)
        application.save(update_fields=['source_removed_delete_after'])
        result = sync_google_sheet(config)

        self.assertEqual(result['deleted'], 0)
        self.assertTrue(Application.objects.filter(id=application.id).exists())
        self.assertTrue(Offer.objects.filter(application=application).exists())
        self.assertTrue(any('a recorded offer' in w['message'] for w in result['warnings']))

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_still_deletes_an_application_with_nothing_of_its_own(self, mock_fetch_sheet_rows):
        config = self._config()
        application, result = self._run_to_deletion(mock_fetch_sheet_rows, config)

        self.assertEqual(result['deleted'], 1)
        self.assertFalse(Application.objects.filter(id=application.id).exists())

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_the_warning_names_the_application_so_it_can_be_acted_on(self, mock_fetch_sheet_rows):
        config = self._config()
        mock_fetch_sheet_rows.return_value = self._both_rows()
        sync_google_sheet(config)
        application = Application.objects.get(user=self.user, company__name='Google')
        Offer.objects.create(application=application, base_salary=165000)

        mock_fetch_sheet_rows.return_value = self._only_stripe()
        sync_google_sheet(config)
        application.refresh_from_db()
        application.source_removed_delete_after = timezone.now() - timedelta(days=1)
        application.save(update_fields=['source_removed_delete_after'])
        result = sync_google_sheet(config)

        message = next(w['message'] for w in result['warnings'] if 'recorded offer' in w['message'])
        self.assertIn('Google', message)
        self.assertIn('Software Engineer', message)
        self.assertIn('Restore its row or delete it here', message)

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_a_stale_tracked_row_does_not_archive_an_application_still_in_the_sheet(
        self, mock_fetch_sheet_rows
    ):
        """The row was matched under one key while an older key for it looked missing."""
        # No external id, which is the shape that makes identity keys the ones under inspection.
        config = GoogleSheetSyncConfig.objects.create(
            user=self.user,
            name='Applications',
            sheet_url='https://docs.google.com/spreadsheets/d/test2/edit',
            spreadsheet_id='test2',
            target_type=GoogleSheetSyncConfig.TARGET_APPLICATIONS,
            column_mapping={
                'company_name': 'Company',
                'role_title': 'Role',
                'status': 'Status',
            },
            missing_row_delete_after_days=5,
        )
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role', 'Status'],
            ['Google', 'Software Engineer', 'Offer'],
        ]
        sync_google_sheet(config)
        application = Application.objects.get(user=self.user, company__name='Google')

        # A second tracked row for the same application, under a key the sheet no longer produces.
        GoogleSheetSyncRow.objects.create(
            config=config,
            external_key='identity:stale0000000000000000',
            row_number=99,
            row_hash='stale',
            local_object_type='career.Application',
            local_object_id=application.id,
        )

        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role', 'Status'],
            ['Google', 'Software Engineer', 'Offer'],
        ]
        result = sync_google_sheet(config)
        application.refresh_from_db()

        self.assertEqual(result['archived'], 0)
        self.assertEqual(result['deleted'], 0)
        self.assertIsNone(application.source_removed_at)
        self.assertNotEqual(application.status, 'REMOVED_FROM_SHEET')
        self.assertFalse(
            GoogleSheetSyncRow.objects.filter(config=config, external_key='identity:stale0000000000000000').exists()
        )
