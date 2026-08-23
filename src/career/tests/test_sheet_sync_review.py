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

class GoogleSheetSyncReviewTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sheet-status-user@example.com",
            email="sheet-status-user@example.com",
            password="StrongPassw0rd!",
        )

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_import_review_detects_new_status_changes_and_possible_duplicates(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Netflix')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            status='ROUND_1',
            salary_range='100000 - 120000',
            location='Remote',
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
                'salary_range': 'Salary',
                'location': 'Location',
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
            ['External ID', 'Company', 'Role', 'Status', 'Salary', 'Location'],
            ['netflix-backend', 'Netflix', 'Backend Engineer', 'Offer', '100000 - 120000', 'Remote'],
            ['', 'Plaid', 'Software Engineer', 'Applied', '148800 - 223200', 'New York, NY'],
            ['', 'Plaid', 'Software Engineer', 'Applied', '148800 - 223200', 'New York, NY'],
        ]

        review = build_import_review(config)

        self.assertEqual(review['summary']['status_changes'], 1)
        self.assertEqual(review['summary']['new_applications'], 1)
        self.assertEqual(review['summary']['possible_duplicates'], 1)
        self.assertEqual(len(review['items']), 3)

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_apply_import_review_only_applies_approved_items(self, mock_fetch_sheet_rows):
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role', 'Status', 'Salary', 'Location'],
            ['Plaid', 'Software Engineer', 'Applied', '148800 - 223200', 'New York, NY'],
            ['Stripe', 'Backend Engineer', 'Applied', '150000 - 180000', 'Remote'],
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
                'status': 'Status',
                'salary_range': 'Salary',
                'location': 'Location',
            },
        )
        review = build_import_review(config)
        plaid_item = next(item for item in review['items'] if item['company_name'] == 'Plaid')

        result = apply_import_review(config, approved_item_ids=[plaid_item['id']])

        self.assertEqual(result['created'], 1)
        self.assertEqual(result['rejected'], 1)
        self.assertTrue(Application.objects.filter(user=self.user, company__name='Plaid').exists())
        self.assertFalse(Application.objects.filter(user=self.user, company__name='Stripe').exists())

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_apply_import_review_can_keep_possible_duplicate_separate(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Plaid')
        Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='APPLIED',
            salary_range='148800 - 223200',
            location='New York, NY',
        )
        mock_fetch_sheet_rows.return_value = [
            ['Company', 'Role', 'Status', 'Salary', 'Location'],
            ['Plaid', 'Software Engineer', 'Applied', '148800 - 223200', 'New York, NY'],
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
                'status': 'Status',
                'salary_range': 'Salary',
                'location': 'Location',
            },
        )
        review = build_import_review(config)
        duplicate_item = review['items'][0]

        result = apply_import_review(
            config,
            approved_item_ids=[duplicate_item['id']],
            duplicate_resolutions={duplicate_item['id']: 'keep_separate'},
        )

        self.assertEqual(result['created'], 1)
        self.assertEqual(
            Application.objects.filter(
                user=self.user,
                company__name='Plaid',
                role_title='Software Engineer',
                salary_range='148800 - 223200',
            ).count(),
            2,
        )
        self.assertTrue(any(entry['type'] == 'duplicate_kept_separate' for entry in result['history']))

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_sync_result_history_records_status_custom_stage_and_duplicate_events(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Plaid')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='APPLIED',
            salary_range='148800 - 223200',
            location='New York, NY',
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
                'salary_range': 'Salary',
                'location': 'Location',
            },
        )
        GoogleSheetSyncRow.objects.create(
            config=config,
            external_key='plaid-ny',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status', 'Salary', 'Location'],
            ['plaid-ny', 'Plaid', 'Software Engineer', '1st Round', '148800 - 223200', 'New York, NY'],
            ['', 'Netflix', 'Backend Engineer', '10th round (bar raiser)', '120000 - 140000', 'Remote'],
            ['', 'Plaid', 'Software Engineer', '1st Round', '148800 - 223200', 'New York, NY'],
        ]

        result = sync_google_sheet(config)

        messages = [entry['message'] for entry in result['history']]
        self.assertTrue(any('Applied -> 1st Round' in message for message in messages))
        self.assertTrue(any(entry['type'] == 'custom_stage_created' and entry['after'] == 'ROUND_10' for entry in result['history']))
        self.assertTrue(any(entry['type'] == 'duplicate_matched' for entry in result['history']))
