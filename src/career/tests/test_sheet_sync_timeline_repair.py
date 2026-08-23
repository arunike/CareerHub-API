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

class GoogleSheetSyncTimelineRepairTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sheet-status-user@example.com",
            email="sheet-status-user@example.com",
            password="StrongPassw0rd!",
        )

    def test_round_status_jump_backfills_missing_timeline_rounds_with_sync_date(self):
        config = type('Config', (), {'user': self.user, 'overwrite_strategies': {}})()

        with patch(
            "career.services.google_sheets.timezone.now",
            return_value=datetime(2026, 5, 19, 16, 0, tzinfo=dt_timezone.utc),
        ):
            application, _, _ = _upsert_application(
                config=config,
                payload={
                    '_user': self.user,
                    'company_name': 'Netflix',
                    'role_title': 'Backend Engineer',
                    'status': '2nd Round',
                },
                tracked=None,
            )

        with patch(
            "career.services.google_sheets.timezone.now",
            return_value=datetime(2026, 5, 20, 16, 0, tzinfo=dt_timezone.utc),
        ):
            _upsert_application(
                config=config,
                payload={
                    '_user': self.user,
                    'company_name': 'Netflix',
                    'role_title': 'Backend Engineer',
                    'status': '4th Round',
                },
                tracked=None,
            )

        entries = {
            entry.stage: entry.event_date
            for entry in ApplicationTimelineEntry.objects.filter(application=application)
        }
        self.assertEqual(entries['ROUND_2'].isoformat(), '2026-05-19')
        self.assertEqual(entries['ROUND_3'].isoformat(), '2026-05-20')
        self.assertEqual(entries['ROUND_4'].isoformat(), '2026-05-20')

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_skipped_existing_sync_repairs_missing_timeline_dates_from_status_change_run(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Netflix')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            status='ROUND_2',
        )
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
        GoogleSheetSyncRow.objects.create(
            config=config,
            external_key='netflix-backend',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['netflix-backend', 'Netflix', 'Backend Engineer', '4th Round'],
        ]

        with patch(
            "career.services.google_sheets.timezone.now",
            return_value=datetime(2026, 5, 20, 16, 0, tzinfo=dt_timezone.utc),
        ):
            sync_google_sheet(config)

        ApplicationTimelineEntry.objects.filter(application=application, stage__in=['ROUND_3', 'ROUND_4']).delete()
        ApplicationTimelineEntry.objects.filter(application=application, stage='ROUND_2').update(event_date=None)

        with patch(
            "career.services.google_sheets.timezone.now",
            return_value=datetime(2026, 5, 25, 16, 0, tzinfo=dt_timezone.utc),
        ):
            second_result = sync_google_sheet(config)

        entries = {
            entry.stage: entry.event_date
            for entry in ApplicationTimelineEntry.objects.filter(application=application)
        }
        self.assertEqual(second_result['skipped'], 1)
        self.assertEqual(entries['ROUND_2'].isoformat(), '2026-05-20')
        self.assertEqual(entries['ROUND_3'].isoformat(), '2026-05-20')
        self.assertEqual(entries['ROUND_4'].isoformat(), '2026-05-20')

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_forced_resync_repairs_missing_timeline_dates_when_fields_do_not_change(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Netflix')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            status='ROUND_4',
        )
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
        GoogleSheetSyncRun.objects.create(
            config=config,
            status=GoogleSheetSyncRun.STATUS_SUCCESS,
            started_at=datetime(2026, 5, 20, 16, 0, tzinfo=dt_timezone.utc),
            changes=[
                {
                    'action': 'updated',
                    'row_number': 2,
                    'diff': {'status': {'old': 'ROUND_2', 'new': 'ROUND_4'}},
                    'local_object_id': application.id,
                }
            ],
        )
        GoogleSheetSyncRow.objects.create(
            config=config,
            external_key='netflix-backend',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['netflix-backend', 'Netflix', 'Backend Engineer', '4th Round'],
        ]

        with patch(
            "career.services.google_sheets.timezone.now",
            return_value=datetime(2026, 5, 25, 16, 0, tzinfo=dt_timezone.utc),
        ):
            result = sync_google_sheet(config, force=True)

        entries = {
            entry.stage: entry.event_date
            for entry in ApplicationTimelineEntry.objects.filter(application=application)
        }
        self.assertEqual(result['updated'], 1)
        self.assertEqual(entries['ROUND_2'].isoformat(), '2026-05-20')
        self.assertEqual(entries['ROUND_3'].isoformat(), '2026-05-20')
        self.assertEqual(entries['ROUND_4'].isoformat(), '2026-05-20')

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_timeline_repair_accepts_from_to_status_history(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Netflix')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            status='ROUND_4',
        )
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
        GoogleSheetSyncRun.objects.create(
            config=config,
            status=GoogleSheetSyncRun.STATUS_SUCCESS,
            started_at=datetime(2026, 5, 20, 16, 0, tzinfo=dt_timezone.utc),
            changes=[
                {
                    'action': 'updated',
                    'row_number': 2,
                    'diff': {'status': {'from': 'ROUND_2', 'to': 'ROUND_4'}},
                    'local_object_id': application.id,
                }
            ],
        )
        GoogleSheetSyncRow.objects.create(
            config=config,
            external_key='netflix-backend',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['netflix-backend', 'Netflix', 'Backend Engineer', '4th Round'],
        ]

        result = sync_google_sheet(config, force=True)

        entries = {
            entry.stage: entry.event_date
            for entry in ApplicationTimelineEntry.objects.filter(application=application)
        }
        self.assertEqual(result['updated'], 1)
        self.assertEqual(entries['ROUND_2'].isoformat(), '2026-05-20')
        self.assertEqual(entries['ROUND_3'].isoformat(), '2026-05-20')
        self.assertEqual(entries['ROUND_4'].isoformat(), '2026-05-20')

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_round_status_drop_hides_later_round_and_preserves_manual_notes(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Netflix')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            status='ROUND_4',
        )
        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='ROUND_3',
            event_date='2026-05-20',
            notes='Old third round detail.',
        )
        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='ROUND_4',
            event_date='2026-05-21',
            notes='Former fourth round detail.',
        )
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
        GoogleSheetSyncRow.objects.create(
            config=config,
            external_key='netflix-backend',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['netflix-backend', 'Netflix', 'Backend Engineer', '3rd Round (2 Tech Interview - System Design + Coding)'],
        ]

        with patch(
            "career.services.google_sheets.timezone.now",
            return_value=datetime(2026, 5, 22, 16, 0, tzinfo=dt_timezone.utc),
        ):
            result = sync_google_sheet(config, force=True)

        application.refresh_from_db()
        visible_entries = {
            entry.stage: entry
            for entry in ApplicationTimelineEntry.objects.filter(
                application=application,
                hidden_by_sync_at__isnull=True,
            )
        }
        hidden_round_four = ApplicationTimelineEntry.objects.get(
            application=application,
            stage='ROUND_4',
        )
        self.assertEqual(result['updated'], 1)
        self.assertEqual(application.status, 'ROUND_3')
        self.assertIn('ROUND_3', visible_entries)
        self.assertEqual(visible_entries['ROUND_3'].event_date.isoformat(), '2026-05-20')
        self.assertEqual(visible_entries['ROUND_3'].notes, 'Old third round detail.')
        self.assertNotIn('ROUND_4', visible_entries)
        self.assertIsNotNone(hidden_round_four.hidden_by_sync_at)
        self.assertEqual(hidden_round_four.notes, 'Former fourth round detail.')

        _ensure_application_timeline_entry(application, 'ROUND_4', '2026-05-23')
        hidden_round_four.refresh_from_db()
        self.assertIsNone(hidden_round_four.hidden_by_sync_at)
        self.assertEqual(hidden_round_four.notes, 'Former fourth round detail.')
