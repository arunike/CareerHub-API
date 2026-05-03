import json
from datetime import datetime, time, timezone as dt_timezone
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import UserSettings
from .models import Application, ApplicationTimelineEntry, Company, Document, Experience, GoogleSheetSyncConfig, GoogleSheetSyncRow
from .serializers import ExperienceSerializer
from .services.google_sheets import _is_sync_config_due, _upsert_application, apply_import_review, build_import_review, sync_google_sheet
from .services.timeline_analytics import build_application_timeline_analytics


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

        analytics = build_application_timeline_analytics(self.user)

        self.assertEqual(analytics['average_time_to_interview_days'], 5)
        self.assertEqual(analytics['time_to_interview_sample_size'], 1)
        screen_stage = next(stage for stage in analytics['stage_conversion'] if stage['key'] == 'SCREEN')
        self.assertEqual(screen_stage['reached_count'], 1)
        self.assertEqual(screen_stage['conversion_rate'], 1)
        self.assertEqual(analytics['offer_rate_by_source'][0]['name'], 'Job Applications')
        self.assertEqual(analytics['offer_rate_by_source'][0]['offers'], 1)

        response = self.client.get('/api/career/application-timeline-analytics/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['average_time_to_interview_days'], 5)

    def test_stale_in_stage_uses_settings_threshold(self):
        company = Company.objects.create(user=self.user, name='Acme')
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


class GoogleSheetApplicationStatusSyncTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sheet-status-user@example.com",
            email="sheet-status-user@example.com",
            password="StrongPassw0rd!",
        )

    def test_parenthesized_round_status_reuses_existing_round_stage(self):
        UserSettings.objects.create(
            user=self.user,
            application_stages=[
                {'key': 'APPLIED', 'label': 'Applied', 'shortLabel': 'Apply', 'tone': 'bg-blue-500'},
                {'key': 'ROUND_2', 'label': '2nd Round', 'shortLabel': 'R2', 'tone': 'bg-amber-500'},
            ],
        )

        application, _ = _upsert_application(
            config=type('Config', (), {'user': self.user})(),
            payload={
                '_user': self.user,
                'company_name': 'Acme',
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
        application, _ = _upsert_application(
            config=type('Config', (), {'user': self.user})(),
            payload={
                '_user': self.user,
                'company_name': 'Acme',
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
        applications = Application.objects.filter(
            user=self.user,
            company__name='Plaid',
            role_title='Software Engineer',
        ).order_by('location')
        self.assertEqual(applications.count(), 2)
        self.assertEqual(
            list(applications.values_list('location', flat=True)),
            ['New York, NY', 'San Francisco, CA'],
        )

        resync_result = sync_google_sheet(config, force=True)
        self.assertEqual(resync_result['created'], 0)
        self.assertEqual(resync_result['updated'], 2)
        self.assertEqual(Application.objects.filter(user=self.user, company__name='Plaid').count(), 2)

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
                location='New York, NY',
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

    @patch("career.services.google_sheets.fetch_sheet_rows")
    def test_import_review_detects_new_status_changes_and_possible_duplicates(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Acme')
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
            external_key='acme-backend',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )

        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status', 'Salary', 'Location'],
            ['acme-backend', 'Acme', 'Backend Engineer', 'Offer', '100000 - 120000', 'Remote'],
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
                location='New York, NY',
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
            ['', 'Acme', 'Backend Engineer', '10th round (bar raiser)', '120000 - 140000', 'Remote'],
            ['', 'Plaid', 'Software Engineer', '1st Round', '148800 - 223200', 'New York, NY'],
        ]

        result = sync_google_sheet(config)

        messages = [entry['message'] for entry in result['history']]
        self.assertTrue(any('Applied -> 1st Round' in message for message in messages))
        self.assertTrue(any(entry['type'] == 'custom_stage_created' and entry['after'] == 'ROUND_10' for entry in result['history']))
        self.assertTrue(any(entry['type'] == 'duplicate_matched' for entry in result['history']))


class ExperienceLogoUploadTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="logo-user@example.com",
            email="logo-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.experience = Experience.objects.create(
            user=self.user,
            title="Software Engineer Intern",
            company="CareerHub",
            is_current=False,
        )

    @patch("career.views.experiences.store_logo_file")
    def test_upload_logo_uses_storage_service_and_persists_url(self, mock_store_logo_file):
        mock_store_logo_file.return_value = "https://blob.vercel-storage.com/experience-logos/test.png"
        buffer = BytesIO()
        Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(buffer, format="PNG")
        logo_file = SimpleUploadedFile(
            "logo.png",
            buffer.getvalue(),
            content_type="image/png",
        )

        response = self.client.post(
            f"/api/career/experiences/{self.experience.id}/upload-logo/",
            {"logo": logo_file},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.experience.refresh_from_db()
        self.assertEqual(self.experience.logo, mock_store_logo_file.return_value)
        self.assertEqual(response.data["logo"], mock_store_logo_file.return_value)
        mock_store_logo_file.assert_called_once()

    @patch("career.views.experiences.delete_logo_asset")
    def test_remove_logo_deletes_asset_and_clears_url(self, mock_delete_logo_asset):
        self.experience.logo = "https://blob.vercel-storage.com/experience-logos/test.png"
        self.experience.save(update_fields=["logo"])

        response = self.client.delete(
            f"/api/career/experiences/{self.experience.id}/remove-logo/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.experience.refresh_from_db()
        self.assertIsNone(self.experience.logo)
        self.assertIsNone(response.data["logo"])
        mock_delete_logo_asset.assert_called_once_with(
            "https://blob.vercel-storage.com/experience-logos/test.png"
        )

    def test_serializer_normalizes_legacy_media_path(self):
        self.experience.logo = "experience_logos/legacy-logo.png"
        serializer = ExperienceSerializer(self.experience)

        self.assertEqual(serializer.data["logo"], "/media/experience_logos/legacy-logo.png")


class JobBoardImportTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="job-import-user@example.com",
            email="job-import-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.url = "/api/career/job-import/"

    @patch("career.services.job_board_import._validate_public_dns")
    @patch("career.services.job_board_import._fetch_html")
    def test_job_import_falls_back_to_rules_without_ai_provider(
        self,
        mock_fetch_html,
        mock_validate_public_dns,
    ):
        mock_fetch_html.return_value = (
            """
            <html>
              <head><title>Software Engineer | Careers at Acme</title></head>
              <body><h1>Software Engineer</h1><p>Location: Remote</p></body>
            </html>
            """,
            "https://careers.acme.com/jobs/software-engineer",
        )

        response = self.client.post(
            self.url,
            {"url": "https://careers.acme.com/jobs/software-engineer"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["company"], "Acme")
        self.assertEqual(response.data["role_title"], "Software Engineer")
        self.assertEqual(response.data["extraction_method"], "rules")
        self.assertEqual(response.data["ai_status"], "not_configured")
        self.assertIn("not configured", response.data["ai_message"])
        mock_validate_public_dns.assert_called()

    @patch("career.services.job_board_import.relay_ai_provider_chat_completion")
    @patch("career.services.job_board_import._validate_public_dns")
    @patch("career.services.job_board_import._fetch_html")
    def test_job_import_uses_ai_when_provider_is_configured(
        self,
        mock_fetch_html,
        mock_validate_public_dns,
        mock_relay_ai_provider_chat_completion,
    ):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.set_ai_provider_api_key("secret-key-1234")
        settings.save()
        mock_fetch_html.return_value = (
            """
            <html>
              <head><title>Careers | Acme</title></head>
              <body>
                <nav>About Acme Products Teams</nav>
                <main>Senior Backend Engineer Location: New York Build APIs for our payments platform.</main>
              </body>
            </html>
            """,
            "https://www.acme.com/careers/backend-engineer",
        )
        mock_relay_ai_provider_chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "company": "Acme",
                                "role_title": "Senior Backend Engineer",
                                "location": "New York",
                                "job_description": "Build APIs for our payments platform.",
                            }
                        )
                    }
                }
            ]
        }

        response = self.client.post(
            self.url,
            {"url": "https://www.acme.com/careers/backend-engineer"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["company"], "Acme")
        self.assertEqual(response.data["role_title"], "Senior Backend Engineer")
        self.assertEqual(response.data["location"], "New York")
        self.assertEqual(response.data["extraction_method"], "ai")
        self.assertEqual(response.data["ai_status"], "success")
        self.assertIn("succeeded", response.data["ai_message"])
        mock_validate_public_dns.assert_called()
        mock_relay_ai_provider_chat_completion.assert_called_once()

    @patch("career.services.job_board_import.relay_ai_provider_chat_completion")
    @patch("career.services.job_board_import._validate_public_dns")
    @patch("career.services.job_board_import._fetch_html")
    def test_job_import_reports_ai_failure_when_falling_back(
        self,
        mock_fetch_html,
        mock_validate_public_dns,
        mock_relay_ai_provider_chat_completion,
    ):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.set_ai_provider_api_key("secret-key-1234")
        settings.save()
        mock_fetch_html.return_value = (
            """
            <html>
              <head><title>Software Engineer | Careers at Acme</title></head>
              <body><h1>Software Engineer</h1><p>Location: Remote</p></body>
            </html>
            """,
            "https://careers.acme.com/jobs/software-engineer",
        )
        mock_relay_ai_provider_chat_completion.side_effect = ValueError("Provider returned malformed JSON.")

        response = self.client.post(
            self.url,
            {"url": "https://careers.acme.com/jobs/software-engineer"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["extraction_method"], "rules")
        self.assertEqual(response.data["ai_status"], "failed")
        self.assertIn("malformed JSON", response.data["ai_message"])
        mock_validate_public_dns.assert_called()
        mock_relay_ai_provider_chat_completion.assert_called_once()


class DocumentStorageFlowTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="document-user@example.com",
            email="document-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    @staticmethod
    def _pdf_file(name="resume.pdf", content=b"%PDF-1.4 test document\n"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    @patch("career.views.documents.store_document_file")
    def test_create_document_uses_storage_service_and_returns_download_url(self, mock_store_document_file):
        mock_store_document_file.return_value = "blob:documents/user-1/root-1/v1/resume.pdf"

        response = self.client.post(
            "/api/career/documents/",
            {
                "title": "Resume",
                "document_type": "RESUME",
                "file": self._pdf_file(),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        document = Document.objects.get()
        self.assertEqual(document.file, "blob:documents/user-1/root-1/v1/resume.pdf")
        self.assertEqual(response.data["file_name"], "resume.pdf")
        self.assertEqual(
            response.data["file"],
            f"http://testserver/api/career/documents/{document.id}/download/",
        )
        mock_store_document_file.assert_called_once()

    @patch("career.views.documents.store_document_file")
    def test_add_version_marks_previous_version_not_current(self, mock_store_document_file):
        root_document = Document.objects.create(
            user=self.user,
            title="Resume",
            file="blob:documents/user-1/root-1/v1/resume.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=True,
        )
        mock_store_document_file.return_value = "blob:documents/user-1/root-1/v2/resume-v2.pdf"

        response = self.client.post(
            f"/api/career/documents/{root_document.id}/add_version/",
            {
                "title": "Resume",
                "document_type": "RESUME",
                "file": self._pdf_file("resume-v2.pdf"),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        root_document.refresh_from_db()
        new_version = Document.objects.get(id=response.data["id"])
        self.assertFalse(root_document.is_current)
        self.assertTrue(new_version.is_current)
        self.assertEqual(new_version.root_document_id, root_document.id)
        self.assertEqual(new_version.version_number, 2)
        self.assertEqual(response.data["file_name"], "resume-v2.pdf")

    @patch("career.views.documents.read_document_bytes")
    def test_download_streams_document_content(self, mock_read_document_bytes):
        mock_read_document_bytes.return_value = b"document-bytes"
        document = Document.objects.create(
            user=self.user,
            title="Resume",
            file="blob:documents/user-1/root-1/v1/resume.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=True,
        )

        response = self.client.get(f"/api/career/documents/{document.id}/download/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content), b"document-bytes")
        self.assertIn('filename="resume.pdf"', response["Content-Disposition"])
        self.assertEqual(response["Content-Length"], str(len(b"document-bytes")))

    @patch("career.signals.delete_document_asset")
    def test_delete_current_document_removes_entire_version_chain(self, mock_delete_document_asset):
        root_document = Document.objects.create(
            user=self.user,
            title="Resume",
            file="blob:documents/user-1/root-1/v1/resume.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=False,
        )
        current_version = Document.objects.create(
            user=self.user,
            title="Resume",
            file="blob:documents/user-1/root-1/v2/resume-v2.pdf",
            document_type="RESUME",
            root_document=root_document,
            version_number=2,
            is_current=True,
        )

        response = self.client.delete(f"/api/career/documents/{current_version.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(mock_delete_document_asset.call_count, 2)

    @patch("career.signals.delete_document_asset")
    def test_delete_all_skips_locked_version_chains(self, mock_delete_document_asset):
        unlocked_root = Document.objects.create(
            user=self.user,
            title="Unlocked Resume",
            file="blob:documents/user-1/root-1/v1/unlocked.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=False,
        )
        Document.objects.create(
            user=self.user,
            title="Unlocked Resume",
            file="blob:documents/user-1/root-1/v2/unlocked-v2.pdf",
            document_type="RESUME",
            root_document=unlocked_root,
            version_number=2,
            is_current=True,
        )
        locked_root = Document.objects.create(
            user=self.user,
            title="Locked Resume",
            file="blob:documents/user-1/root-2/v1/locked.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=False,
        )
        Document.objects.create(
            user=self.user,
            title="Locked Resume",
            file="blob:documents/user-1/root-2/v2/locked-v2.pdf",
            document_type="RESUME",
            root_document=locked_root,
            version_number=2,
            is_current=True,
            is_locked=True,
        )

        response = self.client.delete("/api/career/documents/delete_all/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        remaining_titles = set(Document.objects.values_list("title", flat=True))
        self.assertEqual(remaining_titles, {"Locked Resume"})
        self.assertEqual(mock_delete_document_asset.call_count, 2)
