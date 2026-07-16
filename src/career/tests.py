import json
from datetime import datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import UserSettings
from .models import (
    AIArtifact,
    Application,
    ApplicationTimelineEntry,
    Company,
    Document,
    Experience,
    GoogleSheetSyncConfig,
    GoogleSheetSyncRow,
    GoogleSheetSyncRun,
    Offer,
    application_timeline_stage_order,
)
from .serializers import ExperienceSerializer
from .services.google_sheets import (
    _is_sync_config_due,
    _upsert_application,
    apply_import_review,
    build_import_review,
    sync_google_sheet,
)
from .services.offers import calculate_realizable_equity
from .services.timeline_analytics import build_application_timeline_analytics


class ApplicationTimelineEntryModelTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="timeline-entry-user@example.com",
            email="timeline-entry-user@example.com",
            password="StrongPassw0rd!",
        )
        self.company = Company.objects.create(user=self.user, name='Acme')
        self.application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title='Backend Engineer',
        )

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


class OfferStatusApplicationAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="offer-status-user@example.com",
            email="offer-status-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_offer_status_application_create_creates_offer(self):
        response = self.client.post(
            '/api/career/applications/',
            {
                'company_name': 'Acme',
                'role_title': 'Backend Engineer',
                'status': 'OFFER',
                'salary_range': '120000 - 150000',
                'location': 'New York, NY',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        application = Application.objects.get(id=response.data['id'])
        self.assertTrue(hasattr(application, 'offer'))

        offers_response = self.client.get('/api/career/offers/')
        self.assertEqual(offers_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(offers_response.data), 1)
        self.assertEqual(offers_response.data[0]['application'], application.id)
        self.assertEqual(offers_response.data[0]['application_details']['company'], 'Acme')

    def test_offer_list_backfills_legacy_offer_status_applications(self):
        company = Company.objects.create(user=self.user, name='Plaid')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='OFFER',
            salary_range='148800 - 223200',
        )
        self.assertFalse(Offer.objects.filter(application=application).exists())

        response = self.client.get('/api/career/offers/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['application'], application.id)
        self.assertTrue(Offer.objects.filter(application=application).exists())

    def test_offer_equity_liquidity_fields_round_trip(self):
        company = Company.objects.create(user=self.user, name='Private Co')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='OFFER',
        )
        offer = Offer.objects.create(application=application, base_salary=150000, equity=30000)

        response = self.client.patch(
            f'/api/career/offers/{offer.id}/',
            {
                'equity_liquidity': 'BUYBACK',
                'equity_buyback_value': 18000,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['equity_liquidity'], 'BUYBACK')
        self.assertEqual(Decimal(response.data['equity_buyback_value']), Decimal('18000.00'))
        self.assertEqual(
            calculate_realizable_equity(30000, 'BUYBACK', 18000),
            Decimal('18000'),
        )
        self.assertEqual(calculate_realizable_equity(30000, 'ILLIQUID'), Decimal('0'))


class AIArtifactAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="artifact-user@example.com",
            email="artifact-user@example.com",
            password="StrongPassw0rd!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-artifact-user@example.com",
            email="other-artifact-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_artifacts_are_persisted_searchable_and_user_scoped(self):
        response = self.client.post(
            '/api/career/ai-artifacts/',
            {
                'artifact_type': 'JD_REPORT',
                'client_id': 'local-report-1',
                'title': 'Backend Engineer @ Acme',
                'summary': 'Strong backend match',
                'payload': {
                    'score': 86,
                    'matched_skills': ['Django', 'React'],
                    'missing_skills': ['Kafka'],
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['client_id'], 'local-report-1')

        # Same client_id for the same user updates the existing artifact.
        second_response = self.client.post(
            '/api/career/ai-artifacts/',
            {
                'artifact_type': 'JD_REPORT',
                'client_id': 'local-report-1',
                'title': 'Backend Engineer @ Acme v2',
                'summary': 'Updated',
                'payload': {'score': 91},
            },
            format='json',
        )
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.data['id'], response.data['id'])

        other_client = self.client_class()
        other_client.force_authenticate(self.other_user)
        other_client.post(
            '/api/career/ai-artifacts/',
            {
                'artifact_type': 'COVER_LETTER',
                'client_id': 'other-letter',
                'title': 'Hidden Letter',
                'summary': 'Should not leak',
                'payload': {'coverLetter': 'private'},
            },
            format='json',
        )

        list_response = self.client.get('/api/career/ai-artifacts/', {'search': 'acme'})

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]['title'], 'Backend Engineer @ Acme v2')
        self.assertEqual(list_response.data[0]['payload']['score'], 91)

    def test_locked_artifacts_are_preserved_from_delete_actions(self):
        locked = self.client.post(
            '/api/career/ai-artifacts/',
            {
                'artifact_type': 'NEGOTIATION_RESULT',
                'client_id': 'locked-result',
                'title': 'Locked Result',
                'payload': {'advice': {'leverage_points': []}},
                'is_locked': True,
            },
            format='json',
        ).data
        unlocked = self.client.post(
            '/api/career/ai-artifacts/',
            {
                'artifact_type': 'COVER_LETTER',
                'client_id': 'unlocked-letter',
                'title': 'Unlocked Letter',
                'payload': {'coverLetter': 'hello'},
            },
            format='json',
        ).data

        delete_locked = self.client.delete(f"/api/career/ai-artifacts/{locked['id']}/")
        self.assertEqual(delete_locked.status_code, status.HTTP_403_FORBIDDEN)

        delete_all = self.client.delete('/api/career/ai-artifacts/delete_all/')
        self.assertEqual(delete_all.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_all.data['deleted'], 1)

        remaining = self.client.get('/api/career/ai-artifacts/').data
        self.assertEqual([item['id'] for item in remaining], [locked['id']])
        self.assertFalse(any(item['id'] == unlocked['id'] for item in remaining))

    def test_promotion_review_artifacts_bind_to_user_experience(self):
        experience = Experience.objects.create(
            user=self.user,
            title='Software Engineer',
            company='Acme',
            start_date='2025-01-01',
            is_current=True,
        )
        other_experience = Experience.objects.create(
            user=self.other_user,
            title='Staff Engineer',
            company='OtherCo',
            start_date='2024-01-01',
            is_current=True,
        )

        response = self.client.post(
            '/api/career/ai-artifacts/',
            {
                'artifact_type': 'PROMOTION_REVIEW',
                'client_id': 'promotion-review-1',
                'title': 'Promotion Review - Acme',
                'summary': 'Ready to start the conversation',
                'source_experience': experience.id,
                'payload': {
                    'verdict': {'label': 'Ready to start conversation'},
                    'sourceExperienceId': experience.id,
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['source_experience'], experience.id)

        rejected = self.client.post(
            '/api/career/ai-artifacts/',
            {
                'artifact_type': 'PROMOTION_REVIEW',
                'client_id': 'promotion-review-2',
                'title': 'Invalid Promotion Review',
                'source_experience': other_experience.id,
                'payload': {},
            },
            format='json',
        )

        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)

    def test_application_prep_workspace_collects_linked_materials_and_evidence(self):
        company = Company.objects.create(user=self.user, name='Acme')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            notes='Ask about platform ownership.',
        )
        other_company = Company.objects.create(user=self.other_user, name='OtherCo')
        other_application = Application.objects.create(
            user=self.other_user,
            company=other_company,
            role_title='Hidden Role',
        )
        resume = Document.objects.create(
            user=self.user,
            application=application,
            title='Acme Resume',
            file='https://example.com/resume.pdf',
            document_type='RESUME',
        )
        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='APPLIED',
            event_date='2026-05-08',
            notes='Submitted through referral.',
        )
        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='ROUND_3',
            event_date='2026-06-01',
        )
        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='ROUND_1',
            event_date='2026-05-19',
        )
        ApplicationTimelineEntry.objects.create(
            user=self.user,
            application=application,
            stage='ROUND_2',
            event_date='2026-05-22',
        )
        AIArtifact.objects.create(
            user=self.user,
            artifact_type=AIArtifact.TYPE_JD_REPORT,
            client_id='jd-1',
            title='Acme JD Match',
            summary='Good fit',
            source_application=application,
            payload={
                'score': 84,
                'summary': 'Good fit',
                'best_experiences': [{'title': 'Platform Engineer', 'company': 'OldCo'}],
                'tailored_bullets': [{'revised': 'Built Django services', 'reason': 'Maps to backend work'}],
            },
            saved_at=timezone.now(),
        )
        AIArtifact.objects.create(
            user=self.user,
            artifact_type=AIArtifact.TYPE_COVER_LETTER,
            client_id='letter-1',
            title='Acme Cover Letter',
            payload={'applicationId': application.id, 'coverLetter': 'Dear Acme...'},
            saved_at=timezone.now(),
        )
        AIArtifact.objects.create(
            user=self.other_user,
            artifact_type=AIArtifact.TYPE_JD_REPORT,
            client_id='hidden-jd',
            title='Hidden JD',
            source_application=other_application,
            payload={'score': 99},
            saved_at=timezone.now(),
        )

        response = self.client.get(f'/api/career/applications/{application.id}/prep_workspace/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['application']['id'], application.id)
        self.assertEqual(response.data['notes'], 'Ask about platform ownership.')
        self.assertEqual(response.data['readiness']['linked_documents'], 1)
        self.assertEqual(response.data['documents'][0]['id'], resume.id)
        self.assertEqual(response.data['timeline'][0]['stage'], 'APPLIED')
        self.assertEqual(
            [entry['stage'] for entry in response.data['timeline']],
            ['APPLIED', 'ROUND_1', 'ROUND_2', 'ROUND_3'],
        )
        self.assertEqual(response.data['jd_reports'][0]['title'], 'Acme JD Match')
        self.assertEqual(response.data['cover_letters'][0]['title'], 'Acme Cover Letter')
        self.assertEqual(response.data['latest_jd_report']['payload']['score'], 84)
        self.assertEqual(response.data['evidence']['best_experiences'][0]['title'], 'Platform Engineer')
        self.assertNotIn('Hidden JD', json.dumps(response.data))

    def test_account_export_and_restore_include_ai_artifacts(self):
        self.client.post(
            '/api/career/ai-artifacts/',
            {
                'artifact_type': 'COVER_LETTER',
                'client_id': 'letter-export',
                'title': 'Exported Letter',
                'summary': 'Letter summary',
                'payload': {
                    'applicationId': 123,
                    'companyName': 'Acme',
                    'roleTitle': 'Backend Engineer',
                    'coverLetter': 'Dear team...',
                },
                'is_locked': True,
            },
            format='json',
        )

        export_response = self.client.get('/api/user-settings/account-export/', {'fmt': 'json'})
        self.assertEqual(export_response.status_code, status.HTTP_200_OK)
        payload = json.loads(export_response.content.decode('utf-8'))
        artifacts = payload['career']['ai_artifacts']
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]['client_id'], 'letter-export')
        self.assertEqual(artifacts[0]['payload']['coverLetter'], 'Dear team...')

        backup_file = SimpleUploadedFile(
            'careerhub-account-export.json',
            json.dumps(payload).encode('utf-8'),
            content_type='application/json',
        )
        restore_response = self.client.post(
            '/api/user-settings/restore-backup/',
            {'file': backup_file, 'mode': 'replace'},
            format='multipart',
        )

        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        self.assertEqual(restore_response.data['created_counts']['ai_artifacts'], 1)
        restored = self.client.get('/api/career/ai-artifacts/').data
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]['title'], 'Exported Letter')
        self.assertTrue(restored[0]['is_locked'])


class OfferDecisionSnapshotAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="snapshot-user@example.com",
            email="snapshot-user@example.com",
            password="StrongPassw0rd!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-snapshot-user@example.com",
            email="other-snapshot-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        company = Company.objects.create(user=self.user, name="Acme")
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title="Backend Engineer",
            status="OFFER",
            location="San Francisco, CA",
            office_location="San Francisco, CA",
            rto_policy="HYBRID",
            rto_days_per_week=3,
            commute_cost_value=20,
            commute_cost_frequency="DAILY",
            tax_base_rate=32,
            monthly_rent_override=3500,
        )
        self.offer = Offer.objects.create(
            application=application,
            base_salary=180000,
            bonus=25000,
            equity=60000,
            sign_on=30000,
            benefits_value=12000,
            pto_days=20,
            holiday_days=11,
        )
        other_company = Company.objects.create(user=self.other_user, name="OtherCo")
        other_application = Application.objects.create(
            user=self.other_user,
            company=other_company,
            role_title="Hidden Engineer",
            status="OFFER",
        )
        self.other_offer = Offer.objects.create(
            application=other_application,
            base_salary=1,
            bonus=0,
            equity=0,
            sign_on=0,
            benefits_value=0,
            pto_days=10,
        )

    def _snapshot_payload(self, **overrides):
        payload = {
            "offer": self.offer.id,
            "title": "Decision before onsite counter",
            "notes": "Leaning Acme because adjusted value and team score are strong.",
            "decision_score": 87,
            "rank": 1,
            "total_comp": "307000.00",
            "adjusted_value": "241500.50",
            "monthly_rent": "3500.00",
            "commute_cost_annual": "5200.00",
            "tax_snapshot": {
                "base": 32,
                "bonus": 40,
                "equity": 42,
            },
            "score_categories": [
                {"key": "financial", "label": "Financial", "score": 100, "weight": 44},
                {"key": "team", "label": "Team", "score": 80, "weight": 6},
            ],
            "offer_snapshot": {
                "base_salary": 180000,
                "bonus": 25000,
                "equity": 60000,
                "sign_on": 30000,
                "benefits_value": 12000,
                "company": "Acme",
                "role": "Backend Engineer",
            },
            "adjustment_snapshot": {
                "marital_status": "SINGLE",
                "reference_location": "San Francisco, CA",
            },
        }
        payload.update(overrides)
        return payload

    def test_snapshots_are_created_listed_and_user_scoped(self):
        response = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["company_name"], "Acme")
        self.assertEqual(response.data["role_title"], "Backend Engineer")

        forbidden = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(offer=self.other_offer.id),
            format="json",
        )
        self.assertEqual(forbidden.status_code, status.HTTP_400_BAD_REQUEST)

        list_response = self.client.get(
            "/api/career/offer-decision-snapshots/",
            {"offer": self.offer.id},
        )
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["decision_score"], 87)

    def test_locked_snapshots_are_preserved_from_delete_actions(self):
        locked = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(title="Locked", is_locked=True),
            format="json",
        ).data
        unlocked = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(title="Unlocked"),
            format="json",
        ).data

        delete_locked = self.client.delete(f"/api/career/offer-decision-snapshots/{locked['id']}/")
        self.assertEqual(delete_locked.status_code, status.HTTP_403_FORBIDDEN)

        delete_all = self.client.delete("/api/career/offer-decision-snapshots/delete_all/")
        self.assertEqual(delete_all.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_all.data["deleted"], 1)

        remaining = self.client.get("/api/career/offer-decision-snapshots/").data
        self.assertEqual([item["id"] for item in remaining], [locked["id"]])
        self.assertFalse(any(item["id"] == unlocked["id"] for item in remaining))

    def test_account_export_and_restore_include_offer_decision_snapshots(self):
        self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(is_locked=True),
            format="json",
        )

        export_response = self.client.get("/api/user-settings/account-export/", {"fmt": "json"})
        self.assertEqual(export_response.status_code, status.HTTP_200_OK)
        payload = json.loads(export_response.content.decode("utf-8"))
        snapshots = payload["career"]["offer_decision_snapshots"]
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["offer_company"], "Acme")
        self.assertEqual(snapshots[0]["decision_score"], 87)

        backup_file = SimpleUploadedFile(
            "careerhub-account-export.json",
            json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )
        restore_response = self.client.post(
            "/api/user-settings/restore-backup/",
            {"file": backup_file, "mode": "replace"},
            format="multipart",
        )

        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        self.assertEqual(restore_response.data["created_counts"]["offer_decision_snapshots"], 1)
        restored = self.client.get("/api/career/offer-decision-snapshots/").data
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["title"], "Decision before onsite counter")
        self.assertTrue(restored[0]["is_locked"])


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
        offer = Offer.objects.create(
            application=application,
            base_salary=150000,
        )
        offer.created_at = timezone.make_aware(datetime(2026, 4, 11, 12, 0))
        offer.save()

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

        # Create a manual application with an offer, which should be excluded from sheet sources
        Application.objects.create(
            user=self.user,
            company=company,
            role_title='Manual Engineer',
            status='OFFER',
            date_applied='2026-04-01',
        )

        analytics = build_application_timeline_analytics(self.user)

        self.assertEqual(analytics['average_time_to_interview_days'], 5)
        self.assertEqual(analytics['time_to_interview_sample_size'], 1)
        self.assertEqual(analytics['average_days_to_offer'], 10)
        self.assertEqual(analytics['days_to_offer_sample_size'], 1)
        screen_stage = next(stage for stage in analytics['stage_conversion'] if stage['key'] == 'SCREEN')
        self.assertEqual(screen_stage['reached_count'], 2)
        self.assertEqual(screen_stage['conversion_rate'], 1.0)  # Both applications reached screen (one directly, one via OFFER backfill)
        self.assertEqual(len(analytics['offer_rate_by_source']), 1)
        self.assertEqual(analytics['offer_rate_by_source'][0]['name'], 'Job Applications')
        self.assertEqual(analytics['offer_rate_by_source'][0]['offers'], 1)

        response = self.client.get('/api/career/application-timeline-analytics/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['average_time_to_interview_days'], 5)
        self.assertEqual(response.data['average_days_to_offer'], 10)

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

        application, _, _ = _upsert_application(
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
        application, _, _ = _upsert_application(
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
                    'company_name': 'Acme',
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
                    'company_name': 'Acme',
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
        company = Company.objects.create(user=self.user, name='Acme')
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
            external_key='acme-backend',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['acme-backend', 'Acme', 'Backend Engineer', '4th Round'],
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
        company = Company.objects.create(user=self.user, name='Acme')
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
            external_key='acme-backend',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['acme-backend', 'Acme', 'Backend Engineer', '4th Round'],
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
        company = Company.objects.create(user=self.user, name='Acme')
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
            external_key='acme-backend',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['acme-backend', 'Acme', 'Backend Engineer', '4th Round'],
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
    def test_round_status_drop_removes_later_round_and_preserves_current_stage_notes(self, mock_fetch_sheet_rows):
        company = Company.objects.create(user=self.user, name='Acme')
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
            external_key='acme-backend',
            row_number=2,
            row_hash='old',
            local_object_type='career.Application',
            local_object_id=application.id,
        )
        mock_fetch_sheet_rows.return_value = [
            ['External ID', 'Company', 'Role', 'Status'],
            ['acme-backend', 'Acme', 'Backend Engineer', '3rd Round (2 Tech Interview - System Design + Coding)'],
        ]

        with patch(
            "career.services.google_sheets.timezone.now",
            return_value=datetime(2026, 5, 22, 16, 0, tzinfo=dt_timezone.utc),
        ):
            result = sync_google_sheet(config, force=True)

        application.refresh_from_db()
        entries = {
            entry.stage: entry
            for entry in ApplicationTimelineEntry.objects.filter(application=application)
        }
        self.assertEqual(result['updated'], 1)
        self.assertEqual(application.status, 'ROUND_3')
        self.assertIn('ROUND_3', entries)
        self.assertEqual(entries['ROUND_3'].event_date.isoformat(), '2026-05-20')
        self.assertEqual(entries['ROUND_3'].notes, 'Old third round detail.')
        self.assertNotIn('ROUND_4', entries)

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
              <head>
                <title>Software Engineer | Careers at Acme</title>
                <script type="application/ld+json">
                {
                  "@type": "JobPosting",
                  "title": "Software Engineer",
                  "hiringOrganization": {"name": "Acme"},
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
            {"url": "https://www.acme.com/careers/backend-engineer"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["company"], "Acme")
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

    def test_document_list_supports_server_side_pagination_and_filters(self):
        Company.objects.create(user=self.user, name="Unrelated Co")
        Document.objects.create(
            user=self.user,
            title="Backend Resume",
            file="blob:documents/user-1/root-1/v1/backend-resume.pdf",
            document_type="RESUME",
        )
        Document.objects.create(
            user=self.user,
            title="Frontend Resume",
            file="blob:documents/user-1/root-2/v1/frontend-resume.pdf",
            document_type="RESUME",
        )
        Document.objects.create(
            user=self.user,
            title="Cover Letter",
            file="blob:documents/user-1/root-3/v1/cover-letter.pdf",
            document_type="COVER_LETTER",
        )

        response = self.client.get(
            "/api/career/documents/",
            {
                "page": 1,
                "page_size": 1,
                "search": "resume",
                "document_type": "RESUME",
                "year": str(timezone.now().year),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["document_type"], "RESUME")


class CareerCachingTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="cache-user@example.com",
            email="cache-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_task_caching_and_invalidation(self):
        from django.core.cache import cache
        from .models import Task
        task = Task.objects.create(user=self.user, title="Task 1", status="TODO", position=0)
        
        response1 = self.client.get('/api/career/tasks/')
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response1.data), 1)
        
        Task.objects.filter(id=task.id).update(title="Task 1 Updated")
        
        response2 = self.client.get('/api/career/tasks/')
        self.assertEqual(response2.data[0]['title'], "Task 1")
        
        task.title = "Task 1 Updated Save"
        task.save()
        
        response3 = self.client.get('/api/career/tasks/')
        self.assertEqual(response3.data[0]['title'], "Task 1 Updated Save")

    def test_ai_artifact_caching_and_invalidation(self):
        from django.core.cache import cache
        artifact = AIArtifact.objects.create(
            user=self.user,
            artifact_type='JD_REPORT',
            client_id='art-1',
            title='Art 1',
        )
        
        response1 = self.client.get('/api/career/ai-artifacts/')
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        AIArtifact.objects.filter(id=artifact.id).update(title="Art 1 Updated")
        
        response2 = self.client.get('/api/career/ai-artifacts/')
        self.assertEqual(response2.data[0]['title'], "Art 1")
        
        self.client.delete('/api/career/ai-artifacts/delete_all/')
        
        response3 = self.client.get('/api/career/ai-artifacts/')
        self.assertEqual(len(response3.data), 0)

    def test_application_list_ignores_stale_cached_payload(self):
        from django.core.cache import cache
        from .cache import get_applications_cache_key

        company = Company.objects.create(user=self.user, name="Current Co")
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title="Current Role",
            status="APPLIED",
        )
        cache_key = get_applications_cache_key(self.user.id, "list", {})
        cache.set(
            cache_key,
            [
                {
                    "id": 9283,
                    "role_title": "Stale Role",
                    "company_details": {"name": "Stale Co"},
                }
            ],
            timeout=300,
        )

        response = self.client.get('/api/career/applications/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [application.id])

    def test_application_list_supports_server_side_pagination(self):
        company = Company.objects.create(user=self.user, name="Page Co")
        for index in range(3):
            Application.objects.create(
                user=self.user,
                company=company,
                role_title=f"Role {index + 1}",
                status="APPLIED",
            )

        response = self.client.get('/api/career/applications/', {'page': 2, 'page_size': 2})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(len(response.data['results']), 1)

    def test_application_list_summary_counts_all_matching_records(self):
        company = Company.objects.create(user=self.user, name="Summary Co")
        Application.objects.create(
            user=self.user,
            company=company,
            role_title="Offer Role",
            status="OFFER",
            is_locked=True,
        )
        Application.objects.create(
            user=self.user,
            company=company,
            role_title="Interview Role",
            status="ROUND_3",
        )
        Application.objects.create(
            user=self.user,
            company=company,
            role_title="Applied Role",
            status="APPLIED",
        )

        response = self.client.get('/api/career/applications/', {'page': 1, 'page_size': 1})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['summary']['total'], 3)
        self.assertEqual(response.data['summary']['interviews'], 1)
        self.assertEqual(response.data['summary']['offers'], 1)
        self.assertEqual(response.data['summary']['locked'], 1)

    def test_application_list_orders_status_by_pipeline_progress(self):
        company = Company.objects.create(user=self.user, name="Status Sort Co")
        for status_value in ['APPLIED', 'REJECTED', 'ROUND_2', 'OFFER', 'ROUND_4', 'GHOSTED']:
            Application.objects.create(
                user=self.user,
                company=company,
                role_title=f"{status_value} Role",
                status=status_value,
            )

        asc_response = self.client.get(
            '/api/career/applications/',
            {'page': 1, 'page_size': 6, 'ordering': 'status'},
        )
        desc_response = self.client.get(
            '/api/career/applications/',
            {'page': 1, 'page_size': 6, 'ordering': '-status'},
        )

        self.assertEqual(asc_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item['status'] for item in asc_response.data['results']],
            ['OFFER', 'ROUND_4', 'ROUND_2', 'APPLIED', 'GHOSTED', 'REJECTED'],
        )
        self.assertEqual(
            [item['status'] for item in desc_response.data['results']],
            ['REJECTED', 'GHOSTED', 'APPLIED', 'ROUND_2', 'ROUND_4', 'OFFER'],
        )

    def test_application_list_filters_before_paginating(self):
        houston_company = Company.objects.create(user=self.user, name="Jereh NAG")
        other_company = Company.objects.create(user=self.user, name="Other Co")
        match = Application.objects.create(
            user=self.user,
            company=houston_company,
            role_title="Global IT Software Engineer",
            status="APPLIED",
            employment_type="full_time",
            location="Houston, TX, United States",
            date_applied="2026-05-03",
        )
        Application.objects.create(
            user=self.user,
            company=other_company,
            role_title="Backend Engineer",
            status="ROUND_1",
            employment_type="internship",
            location="New York, NY, United States",
            date_applied="2025-05-03",
        )

        response = self.client.get(
            '/api/career/applications/',
            {
                'page': 1,
                'page_size': 10,
                'search': 'jereh software',
                'status': 'APPLIED',
                'employment_type': 'full_time',
                'location': 'Houston, TX, United States',
                'year': '2026',
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual([item['id'] for item in response.data['results']], [match.id])

    def test_application_options_returns_lightweight_search_results(self):
        backend_company = Company.objects.create(user=self.user, name="Backend Co")
        frontend_company = Company.objects.create(user=self.user, name="Frontend Co")
        match = Application.objects.create(
            user=self.user,
            company=backend_company,
            role_title="Backend Engineer",
            status="APPLIED",
        )
        Application.objects.create(
            user=self.user,
            company=frontend_company,
            role_title="Frontend Engineer",
            status="ROUND_1",
        )

        response = self.client.get(
            "/api/career/applications/options/",
            {"search": "backend", "page_size": 5},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [match.id])
        self.assertEqual(response.data[0]["company_details"]["name"], "Backend Co")
        self.assertNotIn("notes", response.data[0])
