import json
import re
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
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
    CareerRecord,
    Company,
    Contact,
    ContactContext,
    ContactRelationship,
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
    DEFAULT_APPLICATION_STAGES,
    _is_sync_config_due,
    _ensure_application_timeline_entry,
    _round_tone,
    _upsert_application,
    apply_import_review,
    build_import_review,
    sync_google_sheet,
)
from .services.offers import calculate_realizable_equity
from .services.timeline_analytics import build_application_timeline_analytics


class CareerRelationshipNetworkTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='relationships@example.com',
            email='relationships@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_authenticate(self.user)
        self.company = Company.objects.create(user=self.user, name='Northstar Labs')
        self.application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title='Platform Engineer',
            status='OFFER',
        )

    def test_application_gets_one_shared_career_record(self):
        record = CareerRecord.objects.get(application=self.application)

        self.assertEqual(record.user, self.user)
        self.assertEqual(self.application.career_record, record)

    def test_embedded_contact_create_adds_context_and_direct_relationship(self):
        response = self.client.post(
            '/api/career/contacts/',
            {
                'application': self.application.id,
                'name': 'Avery Morgan',
                'email': 'AVERY@EXAMPLE.COM',
                'relationship_kind': 'INTERVIEWER',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        contact = Contact.objects.get(user=self.user)
        self.assertEqual(contact.email, 'avery@example.com')
        self.assertTrue(
            ContactContext.objects.filter(contact=contact, application=self.application).exists()
        )
        self.assertTrue(
            ContactRelationship.objects.filter(
                user=self.user,
                source_contact=None,
                target_contact=contact,
                kind='INTERVIEWER',
            ).exists()
        )

    def test_experience_reuses_email_contact_and_accepts_linked_application(self):
        contact_response = self.client.post(
            '/api/career/contacts/',
            {
                'application': self.application.id,
                'name': 'Rowan Patel',
                'email': 'rowan@example.com',
            },
            format='json',
        )
        offer = Offer.objects.create(application=self.application, base_salary=180000)

        experience_response = self.client.post(
            '/api/career/experiences/',
            {
                'title': 'Platform Engineer',
                'company': 'Northstar Labs',
                'offer': offer.id,
                'is_current': True,
            },
            format='json',
        )
        self.assertEqual(experience_response.status_code, status.HTTP_201_CREATED)
        experience_id = experience_response.data['id']
        second_contact_response = self.client.post(
            '/api/career/contacts/',
            {
                'experience': experience_id,
                'name': 'Rowan P.',
                'email': 'ROWAN@example.com',
                'relationship_kind': 'COWORKER',
            },
            format='json',
        )

        self.assertEqual(contact_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_contact_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Contact.objects.filter(user=self.user).count(), 1)
        self.assertEqual(ContactContext.objects.filter(contact__user=self.user).count(), 2)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'ACCEPTED')
        experience = Experience.objects.get(id=experience_id)
        self.assertEqual(experience.career_record, self.application.career_record)

    def test_indirect_custom_relationship_does_not_create_self_edge(self):
        direct = Contact.objects.create(user=self.user, name='Casey Lin')
        indirect = Contact.objects.create(user=self.user, name='Morgan Reed')
        ContactRelationship.objects.create(
            user=self.user,
            source_contact=None,
            target_contact=direct,
            kind='COWORKER',
        )

        response = self.client.post(
            '/api/career/contact-relationships/',
            {
                'source_contact': direct.id,
                'target_contact': indirect.id,
                'kind': 'CUSTOM',
                'custom_label': 'Skip-level manager',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(
            ContactRelationship.objects.filter(
                user=self.user,
                source_contact=None,
                target_contact=indirect,
            ).exists()
        )

    def test_scoped_delete_detaches_context_without_deleting_person(self):
        response = self.client.post(
            '/api/career/contacts/',
            {'application': self.application.id, 'name': 'Taylor Brooks'},
            format='json',
        )
        contact_id = response.data['id']

        delete_response = self.client.delete(
            f'/api/career/contacts/{contact_id}/?application={self.application.id}'
        )

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(Contact.objects.filter(id=contact_id).exists())
        self.assertFalse(ContactContext.objects.filter(contact_id=contact_id).exists())

    def test_same_name_contacts_are_flagged_but_not_merged(self):
        Contact.objects.create(user=self.user, name='Alex Kim', email='alex.one@example.com')
        Contact.objects.create(user=self.user, name='Alex Kim', email='alex.two@example.com')

        response = self.client.get('/api/career/contacts/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertTrue(all(item['possible_duplicate'] for item in response.data))


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
        company = Company.objects.create(user=self.user, name='Acme')
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

    def test_accepting_offer_marks_application_accepted(self):
        company = Company.objects.create(user=self.user, name='Accepted Co')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Staff Engineer',
            status='OFFER',
        )
        offer = Offer.objects.create(application=application, base_salary=200000)

        response = self.client.patch(
            f'/api/career/offers/{offer.id}/',
            {'final_decision_status': 'ACCEPTED'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        application.refresh_from_db()
        self.assertEqual(application.status, 'ACCEPTED')

    def test_application_endpoint_cannot_mark_offer_accepted(self):
        company = Company.objects.create(user=self.user, name='Manual Accept Co')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            status='OFFER',
        )
        Offer.objects.create(application=application, base_salary=175000)

        response = self.client.patch(
            f'/api/career/applications/{application.id}/',
            {'status': 'ACCEPTED'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['status'][0], 'Accept the offer from the Offers page.')
        application.refresh_from_db()
        self.assertEqual(application.status, 'OFFER')

    def test_reopening_accepted_offer_returns_application_to_offer(self):
        company = Company.objects.create(user=self.user, name='Reopened Co')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Platform Engineer',
            status='ACCEPTED',
        )
        offer = Offer.objects.create(
            application=application,
            base_salary=180000,
            final_decision_status='ACCEPTED',
        )

        response = self.client.patch(
            f'/api/career/offers/{offer.id}/',
            {'final_decision_status': 'PENDING'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        application.refresh_from_db()
        self.assertEqual(application.status, 'OFFER')

    def test_reopening_offer_keeps_application_accepted_when_experience_exists(self):
        company = Company.objects.create(user=self.user, name='Current Co')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Principal Engineer',
            status='ACCEPTED',
        )
        offer = Offer.objects.create(
            application=application,
            base_salary=240000,
            final_decision_status='ACCEPTED',
        )
        Experience.objects.create(
            user=self.user,
            title='Principal Engineer',
            company='Current Co',
            offer=offer,
            is_current=True,
        )

        response = self.client.patch(
            f'/api/career/offers/{offer.id}/',
            {'final_decision_status': 'PENDING'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        application.refresh_from_db()
        self.assertEqual(application.status, 'ACCEPTED')

    def test_application_level_can_be_created_updated_and_read(self):
        create_response = self.client.post(
            '/api/career/applications/',
            {
                'company_name': 'Level Test Co',
                'role_title': 'Software Engineer',
                'status': 'APPLIED',
                'level': 'L4',
            },
            format='json',
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data['level'], 'L4')

        application_id = create_response.data['id']
        update_response = self.client.patch(
            f'/api/career/applications/{application_id}/',
            {'level': 'L5'},
            format='json',
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data['level'], 'L5')

        retrieve_response = self.client.get(f'/api/career/applications/{application_id}/')
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieve_response.data['level'], 'L5')
        self.assertEqual(Application.objects.get(id=application_id).level, 'L5')

    def test_company_list_only_lists_companies_used_by_applications(self):
        used_company = Company.objects.create(user=self.user, name='Used Company')
        second_company = Company.objects.create(user=self.user, name='Another Company')
        Company.objects.create(user=self.user, name='Unused Company')
        Application.objects.create(
            user=self.user,
            company=used_company,
            role_title='Backend Engineer',
        )
        Application.objects.create(
            user=self.user,
            company=used_company,
            role_title='Platform Engineer',
        )
        Application.objects.create(
            user=self.user,
            company=second_company,
            role_title='Frontend Engineer',
        )

        response = self.client.get('/api/career/applications/company-list/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            [
                {'id': second_company.id, 'name': 'Another Company'},
                {'id': used_company.id, 'name': 'Used Company'},
            ],
        )

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
                'sick_leave_days': 10,
                'sick_leave_included_in_unlimited_pto': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['equity_liquidity'], 'BUYBACK')
        self.assertEqual(Decimal(response.data['equity_buyback_value']), Decimal('18000.00'))
        self.assertEqual(response.data['sick_leave_days'], 10)
        self.assertFalse(response.data['sick_leave_included_in_unlimited_pto'])
        self.assertEqual(
            calculate_realizable_equity(30000, 'BUYBACK', 18000),
            Decimal('18000'),
        )
        self.assertEqual(calculate_realizable_equity(30000, 'ILLIQUID'), Decimal('0'))

    def test_offer_defaults_to_zero_sick_leave_days(self):
        company = Company.objects.create(user=self.user, name='Default Leave Co')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='OFFER',
        )

        offer = Offer.objects.create(application=application, base_salary=150000)

        self.assertEqual(offer.sick_leave_days, 0)
        self.assertTrue(offer.sick_leave_included_in_unlimited_pto)


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


class OfferLinkedExperienceSerializerTests(APITestCase):
    """The Past Experience filter on the offers page reads this field, so an offer that
    became a role must be distinguishable from one that never did."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="linked-exp@example.com",
            email="linked-exp@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.company = Company.objects.create(user=self.user, name="Google")

    def _offer(self, role_title, base=100000):
        application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title=role_title,
            status='OFFER',
        )
        return Offer.objects.create(application=application, base_salary=base)

    def test_offer_without_experience_reports_none(self):
        self._offer("Software Engineer")
        response = self.client.get('/api/career/offers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data[0]['linked_experience'])

    def test_offer_with_experience_reports_the_flag_and_dates(self):
        offer = self._offer("Software Engineer")
        Experience.objects.create(
            user=self.user,
            offer=offer,
            title="Software Engineer",
            company="Google",
            start_date=date(2025, 1, 6),
            end_date=date(2026, 8, 14),
            is_current=False,
        )
        response = self.client.get('/api/career/offers/')
        linked = response.data[0]['linked_experience']
        self.assertEqual(linked['title'], "Software Engineer")
        self.assertEqual(linked['company'], "Google")
        self.assertEqual(str(linked['start_date']), '2025-01-06')
        self.assertEqual(str(linked['end_date']), '2026-08-14')
        self.assertFalse(linked['is_current'])

    def test_most_recent_experience_wins(self):
        """An internship and the return offer it became can share one offer."""
        offer = self._offer("Software Engineer")
        Experience.objects.create(
            user=self.user, offer=offer, title="Intern", company="Google",
            start_date=date(2024, 6, 1), end_date=date(2024, 8, 30), is_current=False,
        )
        Experience.objects.create(
            user=self.user, offer=offer, title="Software Engineer", company="Google",
            start_date=date(2025, 1, 6), end_date=None, is_current=True,
        )
        response = self.client.get('/api/career/offers/')
        self.assertEqual(response.data[0]['linked_experience']['title'], "Software Engineer")

    def test_experience_without_start_date_does_not_crash(self):
        offer = self._offer("Software Engineer")
        Experience.objects.create(
            user=self.user, offer=offer, title="Undated", company="Google",
            start_date=None, end_date=None, is_current=False,
        )
        Experience.objects.create(
            user=self.user, offer=offer, title="Also Undated", company="Google",
            start_date=None, end_date=None, is_current=False,
        )
        response = self.client.get('/api/career/offers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data[0]['linked_experience'])


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

    def test_snapshot_accepts_decision_score_above_financial_benchmark(self):
        response = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(
                decision_score=125,
                score_categories=[
                    {"key": "financial", "label": "Financial", "score": 156, "weight": 44},
                    {"key": "team", "label": "Team", "score": 80, "weight": 6},
                ],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["decision_score"], 125)
        self.assertEqual(response.data["score_categories"][0]["score"], 156)

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
                'company_name': 'Acme',
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
                'company_name': 'Acme',
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
    def test_round_status_drop_hides_later_round_and_preserves_manual_notes(self, mock_fetch_sheet_rows):
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
        offer_application = Application.objects.create(
            user=self.user,
            company=company,
            role_title="Offer Role",
            status="OFFER",
            is_locked=True,
        )
        Offer.objects.create(application=offer_application, base_salary=150000)
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

    def test_offer_filter_uses_offer_record_across_final_statuses(self):
        company = Company.objects.create(user=self.user, name="Offer History Co")
        accepted = Application.objects.create(
            user=self.user,
            company=company,
            role_title="Accepted Role",
            status="ACCEPTED",
        )
        declined = Application.objects.create(
            user=self.user,
            company=company,
            role_title="Declined Role",
            status="OFFER_REJECTED",
        )
        accepted_without_offer = Application.objects.create(
            user=self.user,
            company=company,
            role_title="Accepted Without Offer",
            status="ACCEPTED",
        )
        Offer.objects.create(application=accepted, base_salary=170000)
        Offer.objects.create(application=declined, base_salary=160000)

        response = self.client.get(
            '/api/career/applications/',
            {'page': 1, 'page_size': 10, 'status': 'OFFER'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(
            {item['id'] for item in response.data['results']},
            {accepted.id, declined.id},
        )
        self.assertEqual(response.data['summary']['offers'], 2)

        accepted_response = self.client.get(
            '/api/career/applications/',
            {'page': 1, 'page_size': 10, 'status': 'ACCEPTED'},
        )

        self.assertEqual(accepted_response.status_code, status.HTTP_200_OK)
        self.assertEqual(accepted_response.data['count'], 2)
        self.assertEqual(
            {item['id'] for item in accepted_response.data['results']},
            {accepted.id, accepted_without_offer.id},
        )

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


class FunnelConversionPrecisionTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="funnel-precision@example.com",
            email="funnel-precision@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_rare_stage_keeps_enough_precision_to_avoid_reading_as_zero(self):
        """A real count must never be reportable as 0%.

        2 offers out of 806 is 0.248%. Rounded to four decimals that became 0.0025, and the
        display's whole-percent rounding turned it into a flat 0% next to "2 reached" — a
        funnel that looks like it never produced an offer.
        """
        company = Company.objects.create(user=self.user, name='Google')
        applied = timezone.localdate()
        for index in range(806):
            application = Application.objects.create(
                user=self.user,
                company=company,
                role_title=f'Engineer {index}',
                status='OFFER' if index < 2 else 'APPLIED',
                date_applied=applied,
            )
            ApplicationTimelineEntry.objects.create(
                user=self.user,
                application=application,
                stage=application.status,
                event_date=applied,
            )

        data = self.client.get('/api/career/application-timeline-analytics/').json()
        offer = next(row for row in data['stage_conversion'] if row['key'] == 'OFFER')
        self.assertEqual(offer['reached_count'], 2)
        # Enough precision that a one-decimal percentage is non-zero and accurate.
        self.assertAlmostEqual(offer['conversion_rate'], 2 / 806, places=6)
        self.assertGreaterEqual(round(offer['conversion_rate'] * 100, 1), 0.2)


class TimelineAnalyticsInsightTests(APITestCase):
    """The four additions: real offer dates, reply timing, response-rate segments, stage durations."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="timeline-insight@example.com",
            email="timeline-insight@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        UserSettings.objects.create(user=self.user, ghosting_threshold_days=30)
        self.today = timezone.localdate()

    def _app(self, name, status, applied, entries=(), level='', location=''):
        company, _ = Company.objects.get_or_create(user=self.user, name=name)
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Engineer',
            status=status,
            date_applied=applied,
            level=level,
            office_location=location,
        )
        for stage, event_date in entries:
            ApplicationTimelineEntry.objects.create(
                user=self.user, application=application, stage=stage, event_date=event_date
            )
        return application

    def _analytics(self):
        return self.client.get('/api/career/application-timeline-analytics/').json()

    def test_days_to_offer_uses_the_offer_date_not_when_the_record_was_typed_in(self):
        applied = self.today - timedelta(days=400)
        offer_arrived = applied + timedelta(days=30)
        application = self._app(
            'Google', 'ACCEPTED', applied,
            entries=[('APPLIED', applied), ('OFFER', offer_arrived)],
        )
        # Backfilled today, long after the offer actually arrived.
        Offer.objects.create(application=application, base_salary=Decimal('100000'))

        data = self._analytics()
        # 30, from the timeline — not ~400, which is when the Offer row was created.
        self.assertEqual(data['average_days_to_offer'], 30)
        self.assertEqual(data['days_to_offer_sample_size'], 1)

    def test_days_to_offer_falls_back_to_the_record_when_no_timeline_entry_exists(self):
        applied = self.today - timedelta(days=10)
        application = self._app('Acme', 'OFFER', applied, entries=[('APPLIED', applied)])
        Offer.objects.create(application=application, base_salary=Decimal('100000'))

        data = self._analytics()
        # No OFFER entry to read, so the record's creation date is all there is: 10 days.
        self.assertEqual(data['average_days_to_offer'], 10)

    def test_reply_timing_buckets_and_followup_cutoff(self):
        # Replies at 2, 5, 20 and 45 days, plus one that never answered.
        for index, delay in enumerate([2, 5, 20, 45]):
            applied = self.today - timedelta(days=90)
            self._app(
                f'Company {index}', 'SCREEN', applied,
                entries=[('APPLIED', applied), ('SCREEN', applied + timedelta(days=delay))],
            )
        silent_applied = self.today - timedelta(days=70)
        self._app('Silent', 'APPLIED', silent_applied, entries=[('APPLIED', silent_applied)])

        data = self._analytics()
        self.assertEqual(data['response_time_sample_size'], 4)
        buckets = {row['label']: row['count'] for row in data['response_time_buckets']}
        self.assertEqual(buckets['0-7 days'], 2)
        self.assertEqual(buckets['15-30 days'], 1)
        self.assertEqual(buckets['31-60 days'], 1)
        # Cumulative share is monotonic and ends at everything.
        shares = [row['cumulative_share'] for row in data['response_time_buckets']]
        self.assertEqual(shares, sorted(shares))
        self.assertEqual(shares[-1], 1)
        # p90 of [2, 5, 20, 45] by nearest rank is 45; the cutoff follows the distribution
        # rather than snapping up to a bucket edge.
        self.assertEqual(data['p90_days_to_response'], 45)
        self.assertEqual(data['suggested_followup_days'], 45)
        # The silent one has waited 70 days, past that cutoff.
        self.assertEqual(data['open_without_response_count'], 1)
        self.assertEqual(data['silent_past_followup_count'], 1)

    def test_response_segments_report_rate_with_sample_size(self):
        applied = self.today - timedelta(days=60)
        # Palo Alto: 1 of 2 replied. Remote: 0 of 1.
        self._app('A', 'SCREEN', applied, entries=[('APPLIED', applied), ('SCREEN', applied)], location='Palo Alto, CA')
        self._app('B', 'APPLIED', applied, entries=[('APPLIED', applied)], location='Palo Alto, CA')
        self._app('C', 'APPLIED', applied, entries=[('APPLIED', applied)], location='Remote - US')

        rows = {row['name']: row for row in self._analytics()['response_rate_by_location']}
        self.assertEqual(rows['Palo Alto']['total'], 2)
        self.assertEqual(rows['Palo Alto']['responded'], 1)
        self.assertAlmostEqual(rows['Palo Alto']['response_rate'], 0.5)
        self.assertEqual(rows['Remote']['responded'], 0)
        # The sample size travels with the rate so a caller can refuse to show n=1.
        self.assertEqual(rows['Remote']['total'], 1)

    def test_rejected_after_interviewing_still_counts_as_a_response(self):
        applied = self.today - timedelta(days=60)
        self._app(
            'Rejector', 'REJECTED', applied,
            entries=[('APPLIED', applied), ('SCREEN', applied + timedelta(days=3)), ('REJECTED', applied + timedelta(days=9))],
        )
        data = self._analytics()
        # Status alone says rejected; the timeline says they replied in 3 days.
        self.assertEqual(data['response_time_sample_size'], 1)
        self.assertEqual(data['median_days_to_response'], 3)

    def test_stage_durations_and_per_stage_staleness_context(self):
        # Three applications that each took 10 days to move from 1st to 2nd round, so the
        # stage has enough history to call 10 days typical.
        for index in range(3):
            applied = self.today - timedelta(days=120)
            self._app(
                f'Mover {index}', 'REJECTED', applied,
                entries=[
                    ('APPLIED', applied),
                    ('ROUND_1', applied + timedelta(days=5)),
                    ('ROUND_2', applied + timedelta(days=15)),
                ],
            )
        # One still sitting in 1st round, 100 days in.
        stuck_applied = self.today - timedelta(days=100)
        self._app('Stuck', 'ROUND_1', stuck_applied, entries=[('APPLIED', stuck_applied), ('ROUND_1', stuck_applied)])

        data = self._analytics()
        durations = {row['key']: row for row in data['stage_durations']}
        self.assertEqual(durations['ROUND_1']['median_days'], 10)
        self.assertEqual(durations['ROUND_1']['sample_size'], 3)

        stuck = next(row for row in data['stale_in_stage'] if row['company'] == 'Stuck')
        self.assertEqual(stuck['days_in_stage'], 100)
        self.assertEqual(stuck['typical_days'], 10)
        self.assertEqual(stuck['days_over_typical'], 90)

    def test_a_single_transition_is_not_treated_as_a_typical_duration(self):
        applied = self.today - timedelta(days=120)
        self._app(
            'Lonely', 'REJECTED', applied,
            entries=[('APPLIED', applied), ('ROUND_3', applied + timedelta(days=1)), ('ROUND_4', applied + timedelta(days=60))],
        )
        stuck_applied = self.today - timedelta(days=90)
        self._app('Stuck', 'ROUND_3', stuck_applied, entries=[('APPLIED', stuck_applied), ('ROUND_3', stuck_applied)])

        data = self._analytics()
        durations = {row['key']: row for row in data['stage_durations']}
        # Reported with its sample size...
        self.assertEqual(durations['ROUND_3']['sample_size'], 1)
        self.assertLess(durations['ROUND_3']['sample_size'], data['min_duration_sample'])
        # ...but not used as a comparison, so nothing is flagged against an anecdote.
        stuck = next(row for row in data['stale_in_stage'] if row['company'] == 'Stuck')
        self.assertIsNone(stuck['typical_days'])
        self.assertIsNone(stuck['days_over_typical'])


class ApplicationStatsAPITests(APITestCase):
    """The dashboard's counts moved from the browser to the server.

    These pin the bucket definitions the frontend used to own, so a change here is a
    deliberate change to the dashboard rather than a silent one.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="application-stats-user@example.com",
            email="application-stats-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.today = timezone.localdate()

    def _application(self, status_value, *, applied=None, location='', office='', round_no=0):
        company, _ = Company.objects.get_or_create(user=self.user, name='Google')
        return Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status=status_value,
            date_applied=applied,
            location=location,
            office_location=office,
            current_round=round_no,
        )

    def test_counts_match_the_definitions_the_dashboard_uses(self):
        self._application('APPLIED', applied=self.today)
        self._application('SCREEN', applied=self.today)
        self._application('OFFER', applied=self.today)
        self._application('ACCEPTED', applied=self.today)
        self._application('OFFER_REJECTED', applied=self.today)
        self._application('GHOSTED', applied=self.today)
        # A rejection only counts as an interview when a round was actually reached.
        self._application('REJECTED', applied=self.today, round_no=0)
        self._application('REJECTED', applied=self.today, round_no=2)

        response = self.client.get('/api/career/application-stats/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['total'], 8)
        # OFFER, ACCEPTED and OFFER_REJECTED all count as an offer having been made.
        self.assertEqual(data['offers'], 3)
        self.assertEqual(data['ghosted'], 1)
        # Everything except APPLIED, REJECTED, GHOSTED, ACCEPTED and REMOVED_FROM_SHEET.
        self.assertEqual(data['active_interviews'], 3)
        # SCREEN, OFFER, ACCEPTED, OFFER_REJECTED, and only the rejection with a round.
        self.assertEqual(data['total_interviews'], 5)
        # Everything except APPLIED, GHOSTED and REMOVED_FROM_SHEET.
        self.assertEqual(data['responded_count'], 6)
        self.assertEqual(data['response_rate'], '75.0')
        self.assertEqual(data['offer_rate'], '37.5')

    def test_locations_group_to_city_and_collapse_remote(self):
        self._application('APPLIED', applied=self.today, office='New York, NY')
        self._application('APPLIED', applied=self.today, office='New York, NY')
        self._application('APPLIED', applied=self.today, location='Remote - US')
        self._application('APPLIED', applied=self.today, location='fully remote')
        self._application('APPLIED', applied=self.today)

        data = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(
            {row['name']: row['count'] for row in data['locations']},
            {'New York': 2, 'Remote': 2, 'Unknown': 1},
        )
        # Sorted by count, so the dashboard's "top locations" list needs no client sort.
        self.assertGreaterEqual(data['locations'][0]['count'], data['locations'][-1]['count'])

    def test_age_buckets_and_recent_window(self):
        self._application('APPLIED', applied=self.today)
        self._application('APPLIED', applied=self.today - timedelta(days=20))
        self._application('APPLIED', applied=self.today - timedelta(days=60))
        self._application('APPLIED', applied=self.today - timedelta(days=200))
        # Age falls back to created_at, so a row with no applied date is aged from when it
        # was added rather than dropped into Undated. Undated needs both to be missing,
        # which auto-set created_at makes unreachable in practice.
        self._application('APPLIED', applied=None)

        data = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(
            {row['name']: row['count'] for row in data['application_age_breakdown']},
            {'Last 7 days': 2, '8-30 days': 1, '31-90 days': 1, '90+ days': 1},
        )
        # Today, 20 days ago, and the created-today fallback. The 60- and 200-day rows are
        # out, and an application dated a full 30 days ago would be out too.
        self.assertEqual(data['recent_applications_30d'], 3)

    def test_thirty_day_window_excludes_the_boundary_day(self):
        self._application('APPLIED', applied=self.today - timedelta(days=29))
        self._application('APPLIED', applied=self.today - timedelta(days=30))

        data = self.client.get('/api/career/application-stats/').json()
        # The browser compared a wall-clock instant against midnight, so a date exactly 30
        # days old already fell outside the window. Held here so the tile does not shift.
        self.assertEqual(data['recent_applications_30d'], 1)

    def test_daily_histogram_replaces_the_application_list(self):
        self._application('APPLIED', applied=self.today)
        self._application('APPLIED', applied=self.today)
        self._application('APPLIED', applied=self.today - timedelta(days=1))
        self._application('APPLIED', applied=None)

        data = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(
            data['daily_applied'],
            {
                (self.today - timedelta(days=1)).isoformat(): 1,
                self.today.isoformat(): 2,
            },
        )
        # Undated rows cannot be placed on the chart, so they are left out of the histogram.
        self.assertEqual(sum(data['daily_applied'].values()), 3)

    def test_year_filter_narrows_counts_but_never_the_year_list(self):
        self._application('APPLIED', applied=date(2024, 5, 1))
        self._application('APPLIED', applied=date(2026, 5, 1))
        self._application('APPLIED', applied=date(2026, 6, 1))

        unfiltered = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(unfiltered['total'], 3)
        self.assertEqual(unfiltered['years'], [2026, 2024])

        filtered = self.client.get('/api/career/application-stats/?year=2026').json()
        self.assertEqual(filtered['total'], 2)
        # The picker must keep every year, or selecting one would strand the user on it.
        self.assertEqual(filtered['years'], [2026, 2024])

        for value in ('all', 'garbage', ''):
            with self.subTest(year=value):
                self.assertEqual(
                    self.client.get(f'/api/career/application-stats/?year={value}').json()['total'],
                    3,
                )

    def test_stats_are_scoped_to_the_requesting_user(self):
        other = get_user_model().objects.create_user(
            username="other-stats-user@example.com",
            email="other-stats-user@example.com",
            password="StrongPassw0rd!",
        )
        other_company = Company.objects.create(user=other, name='Acme')
        Application.objects.create(
            user=other,
            company=other_company,
            role_title='Engineer',
            status='OFFER',
            date_applied=self.today,
        )
        self._application('APPLIED', applied=self.today)

        data = self.client.get('/api/career/application-stats/').json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['offers'], 0)

    def test_stats_require_authentication(self):
        self.client.force_authenticate(None)
        response = self.client.get('/api/career/application-stats/')
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


class ApplicationListQueryCountTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="application-query-count@example.com",
            email="application-query-count@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_list_does_not_scale_queries_with_row_count(self):
        """The serializer nests the offer, its experiences, and submitted documents.

        Without select_related/prefetch_related each row cost two extra queries, so a real
        account's 808 applications issued 1623. This pins the count so it cannot regress:
        ten applications must cost the same number of queries as two.
        """
        company = Company.objects.create(user=self.user, name='Google')

        def make(index):
            application = Application.objects.create(
                user=self.user,
                company=company,
                role_title=f'Engineer {index}',
                status='OFFER',
                date_applied=timezone.localdate(),
            )
            Offer.objects.create(application=application, base_salary=Decimal('100000'))
            document = Document.objects.create(user=self.user, title=f'Resume {index}')
            application.submitted_documents.add(document)
            return application

        for index in range(2):
            make(index)
        with CaptureQueriesContext(connection) as small:
            self.assertEqual(len(self.client.get('/api/career/applications/').json()), 2)

        for index in range(2, 10):
            make(index)
        with CaptureQueriesContext(connection) as large:
            self.assertEqual(len(self.client.get('/api/career/applications/').json()), 10)

        # The absolute number is not the point; not growing with the row count is.
        self.assertEqual(
            len(large.captured_queries),
            len(small.captured_queries),
            f'5x the rows cost {len(large.captured_queries)} queries instead of '
            f'{len(small.captured_queries)} — a prefetch was probably dropped.',
        )
        self.assertLess(len(large.captured_queries), 10)
