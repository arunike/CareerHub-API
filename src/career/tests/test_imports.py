import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import UserSettings
from ..models import Application, Company, Offer


class ApplicationFileImportPreviewTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="file-import-user@example.com",
            email="file-import-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_upload_returns_preview_and_apply_creates_rows_with_multilingual_headers(self):
        upload = SimpleUploadedFile(
            "applications.csv",
            "公司,职位,状态,薪资\nGoogle,Software Engineer,1st Round,150k\n".encode("utf-8"),
            content_type="text/csv",
        )

        preview_response = self.client.post("/api/career/import/", {"file": upload}, format="multipart")

        self.assertEqual(preview_response.status_code, status.HTTP_200_OK)
        self.assertEqual(Application.objects.filter(user=self.user).count(), 0)
        preview = preview_response.data["preview"]
        self.assertEqual(preview["mapping"]["company_name"], "公司")
        self.assertEqual(preview["mapping"]["role_title"], "职位")
        self.assertEqual(preview["mapping"]["status"], "状态")
        self.assertEqual(preview["summary"]["creates"], 1)

        apply_response = self.client.post(
            "/api/career/import/apply/",
            {"rows": preview["rows"], "mapping": preview["mapping"]},
            format="json",
        )

        self.assertEqual(apply_response.status_code, status.HTTP_200_OK)
        self.assertEqual(apply_response.data["result"]["created"], 1)
        application = Application.objects.get(user=self.user, company__name="Google")
        self.assertEqual(application.role_title, "Software Engineer")
        self.assertEqual(application.status, "ROUND_1")

    @patch("career.services.application_imports.relay_ai_provider_chat_completion")
    def test_ai_mapping_handles_unknown_headers_before_user_confirmation(self, mock_relay):
        settings_profile = UserSettings.objects.create(
            user=self.user,
            ai_provider_adapter="openai",
            ai_provider_endpoint="https://api.example.com/v1/chat/completions",
            ai_provider_model="gpt-test",
        )
        settings_profile.set_ai_provider_api_key("secret-key")
        settings_profile.save(update_fields=["ai_provider_api_key_encrypted"])
        mock_relay.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "company_name": "雇用主",
                            "role_title": "募集職種",
                            "job_link": "応募URL",
                        })
                    }
                }
            ]
        }
        upload = SimpleUploadedFile(
            "applications.csv",
            "雇用主,募集職種,応募URL\nStripe,Backend Engineer,https://example.com/job\n".encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post("/api/career/import/", {"file": upload}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        preview = response.data["preview"]
        self.assertEqual(preview["ai_status"], "success")
        self.assertEqual(preview["mapping"]["company_name"], "雇用主")
        self.assertEqual(preview["mapping"]["role_title"], "募集職種")
        self.assertEqual(Application.objects.filter(user=self.user).count(), 0)
        mock_relay.assert_called_once()

    def test_apply_updates_existing_matching_application(self):
        company = Company.objects.create(user=self.user, name="OpenAI")
        Application.objects.create(
            user=self.user,
            company=company,
            role_title="Product Engineer",
            status="APPLIED",
            salary_range="100k",
        )
        rows = [{"Company": "OpenAI", "Role": "Product Engineer", "Status": "Offer", "Salary": "200k"}]
        mapping = {
            "company_name": "Company",
            "role_title": "Role",
            "status": "Status",
            "salary_range": "Salary",
        }

        response = self.client.post(
            "/api/career/import/apply/",
            {"rows": rows, "mapping": mapping},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["result"]["created"], 0)
        self.assertEqual(response.data["result"]["updated"], 1)
        self.assertEqual(Application.objects.filter(user=self.user, company__name="OpenAI").count(), 1)
        application = Application.objects.get(user=self.user, company__name="OpenAI")
        self.assertEqual(application.status, "OFFER")
        self.assertEqual(application.salary_range, "200k")


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
              <head>
                <title>Software Engineer | Careers at Google</title>
                <script type="application/ld+json">
                {
                  "@type": "JobPosting",
                  "title": "Software Engineer",
                  "hiringOrganization": {"name": "Google"},
                  "employmentType": "FULL_TIME",
                  "jobLocation": {"address": {"addressLocality": "Remote"}},
                  "baseSalary": {
                    "currency": "USD",
                    "value": {"minValue": 150000, "maxValue": 180000, "unitText": "YEAR"}
                  }
                }
                </script>
              </head>
              <body><h1>Software Engineer</h1><p>Location: Remote</p></body>
            </html>
            """,
            "https://careers.google.com/jobs/software-engineer",
        )

        response = self.client.post(
            self.url,
            {"url": "https://careers.google.com/jobs/software-engineer"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["company"], "Google")
        self.assertEqual(response.data["role_title"], "Software Engineer")
        self.assertEqual(response.data["employment_type"], "full_time")
        self.assertEqual(response.data["salary_range"], "$150k - $180k year")
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
              <head><title>Careers | Google</title></head>
              <body>
                <nav>About Google Products Teams</nav>
                <main>Senior Backend Engineer Location: New York Build APIs for our payments platform.</main>
              </body>
            </html>
            """,
            "https://www.google.com/careers/backend-engineer",
        )
        mock_relay_ai_provider_chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "company": "Google",
                                "role_title": "Senior Backend Engineer",
                                "location": "New York",
                                "employment_type": "contract",
                                "salary_range": "$80 - $100/hour",
                                "job_description": "Build APIs for our payments platform.",
                            }
                        )
                    }
                }
            ]
        }

        response = self.client.post(
            self.url,
            {"url": "https://www.google.com/careers/backend-engineer"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["company"], "Google")
        self.assertEqual(response.data["role_title"], "Senior Backend Engineer")
        self.assertEqual(response.data["location"], "New York")
        self.assertEqual(response.data["employment_type"], "contract")
        self.assertEqual(response.data["salary_range"], "$80 - $100/hour")
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
              <head><title>Software Engineer | Careers at Google</title></head>
              <body><h1>Software Engineer</h1><p>Location: Remote</p></body>
            </html>
            """,
            "https://careers.google.com/jobs/software-engineer",
        )
        mock_relay_ai_provider_chat_completion.side_effect = ValueError("Provider returned malformed JSON.")

        response = self.client.post(
            self.url,
            {"url": "https://careers.google.com/jobs/software-engineer"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["extraction_method"], "rules")
        self.assertEqual(response.data["ai_status"], "failed")
        self.assertIn("malformed JSON", response.data["ai_message"])
        mock_validate_public_dns.assert_called()
        mock_relay_ai_provider_chat_completion.assert_called_once()
