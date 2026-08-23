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

class GoogleSheetSyncIdentityTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sheet-status-user@example.com",
            email="sheet-status-user@example.com",
            password="StrongPassw0rd!",
        )

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_same_company_and_role_with_different_locations_create_distinct_applications(self, mock_fetch_sheet_rows):
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role', 'Salary', 'Location'],
            ['Plaid', 'Software Engineer', '148800 - 223200', 'New York, NY'],
            ['Plaid', 'Software Engineer', '148800 - 223200', 'San Francisco, CA'],
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
                'salary_range': 'Salary',
                'location': 'Location',
            },
        )

        result = sync_google_sheet(config)

        self.assertEqual(result['created'], 2)
        self.assertEqual(result['errors'], [])
        config.refresh_from_db()
        latest_run = config.runs.latest('id')
        self.assertEqual(len(latest_run.changes), 2)
        self.assertTrue(all(change['local_object_id'] for change in latest_run.changes))
        applications = Application.objects.filter(
            user=self.user,
            company__name='Plaid',
            role_title='Software Engineer',
        ).order_by('location')
        self.assertEqual(applications.count(), 2)
        self.assertEqual(
            list(applications.values_list('location', flat=True)),
            ['New York, NY, United States', 'San Francisco, CA, United States'],
        )

        resync_result = sync_google_sheet(config, force=True)
        self.assertEqual(resync_result['created'], 0)
        self.assertEqual(resync_result['updated'], 2)
        self.assertEqual(Application.objects.filter(user=self.user, company__name='Plaid').count(), 2)

        unchanged_result = sync_google_sheet(config)
        self.assertEqual(unchanged_result['skipped'], 2)
        self.assertEqual(unchanged_result['errors'], [])

    @patch("career.services.google_sheets.timezone.now")
    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_missing_date_applied_uses_user_timezone_today(self, mock_fetch_sheet_rows, mock_now):
        mock_now.return_value = datetime(2026, 5, 5, 4, 30, tzinfo=dt_timezone.utc)
        UserSettings.objects.create(user=self.user, primary_timezone='America/Los_Angeles')
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role'],
            ['OpenAI', 'Product Engineer'],
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

        result = sync_google_sheet(config)

        self.assertEqual(result['errors'], [])
        application = Application.objects.get(user=self.user, company__name='OpenAI')
        self.assertEqual(application.date_applied.isoformat(), '2026-05-04')

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_sheet_location_maps_to_canonical_us_city_location(self, mock_fetch_sheet_rows):
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role', 'Location', 'Office Location'],
            ['OpenAI', 'Product Engineer', 'San Francisco, CA', 'New York, NY, United States'],
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
                'location': 'Location',
                'office_location': 'Office Location',
            },
        )

        result = sync_google_sheet(config)

        self.assertEqual(result['errors'], [])
        application = Application.objects.get(user=self.user, company__name='OpenAI')
        self.assertEqual(application.location, 'San Francisco, CA, United States')
        self.assertEqual(application.office_location, 'New York, NY, United States')

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_canonical_location_sync_matches_existing_legacy_location(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='OpenAI')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Product Engineer',
            location='San Francisco, CA',
        )
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role', 'Location'],
            ['OpenAI', 'Product Engineer', 'San Francisco, CA'],
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
                'location': 'Location',
            },
        )

        result = sync_google_sheet(config)

        self.assertEqual(result['errors'], [])
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['updated'], 1)
        application.refresh_from_db()
        self.assertEqual(application.location, 'San Francisco, CA, United States')

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_identical_company_role_salary_and_location_dedupes_application(self, mock_fetch_sheet_rows):
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role', 'Salary', 'Location'],
            ['Plaid', 'Software Engineer', '148800 - 223200', 'New York, NY'],
            ['Plaid', 'Software Engineer', '148800 - 223200', 'New York, NY'],
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
                'salary_range': 'Salary',
                'location': 'Location',
            },
        )

        result = sync_google_sheet(config)

        self.assertEqual(result['created'], 1)
        self.assertEqual(result['updated'], 1)
        self.assertEqual(
            Application.objects.filter(
                user=self.user,
                company__name='Plaid',
                role_title='Software Engineer',
                salary_range='148800 - 223200',
                location='New York, NY, United States',
            ).count(),
            1,
        )

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_unchanged_tracked_row_backfills_missing_date_applied(self, mock_fetch_sheet_rows):
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role', 'Location'],
            ['1Password', 'Developer, Backend', 'Remote'],
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
                'location': 'Location',
            },
        )

        sync_google_sheet(config)
        application = Application.objects.get(user=self.user, company__name='1Password')
        original_date = application.date_applied
        application.date_applied = None
        application.save(update_fields=['date_applied'])

        result = sync_google_sheet(config)

        application.refresh_from_db()
        self.assertEqual(result['updated'], 1)
        self.assertEqual(result['skipped'], 0)
        self.assertEqual(application.date_applied, original_date)
        self.assertTrue(
            any(entry['type'] == 'date_applied_backfilled' for entry in result['history'])
        )

    def test_sync_config_due_respects_local_time_and_same_day_sync(self):
        config = GoogleSheetSyncConfig.objects.create(
            user=self.user,
            name='Applications',
            sheet_url='https://docs.google.com/spreadsheets/d/test/edit',
            spreadsheet_id='test',
            target_type=GoogleSheetSyncConfig.TARGET_APPLICATIONS,
            sync_time=time(10, 0),
            sync_timezone='America/Los_Angeles',
        )

        before_window = datetime(2026, 5, 2, 16, 30, tzinfo=dt_timezone.utc)
        after_window = datetime(2026, 5, 2, 17, 30, tzinfo=dt_timezone.utc)

        self.assertFalse(_is_sync_config_due(config, now=before_window))
        self.assertTrue(_is_sync_config_due(config, now=after_window))

        config.last_synced_at = after_window
        self.assertFalse(_is_sync_config_due(config, now=datetime(2026, 5, 2, 18, 30, tzinfo=dt_timezone.utc)))
        self.assertTrue(_is_sync_config_due(config, now=datetime(2026, 5, 3, 17, 30, tzinfo=dt_timezone.utc)))
