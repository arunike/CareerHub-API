import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import AIArtifact, Application, ApplicationTimelineEntry, Company, Document, Experience


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
                'title': 'Backend Engineer @ Google',
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
                'title': 'Backend Engineer @ Google v2',
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

        list_response = self.client.get('/api/career/ai-artifacts/', {'search': 'google'})

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]['title'], 'Backend Engineer @ Google v2')
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
            company='Google',
            start_date='2025-01-01',
            is_current=True,
        )
        other_experience = Experience.objects.create(
            user=self.other_user,
            title='Staff Engineer',
            company='Netflix',
            start_date='2024-01-01',
            is_current=True,
        )

        response = self.client.post(
            '/api/career/ai-artifacts/',
            {
                'artifact_type': 'PROMOTION_REVIEW',
                'client_id': 'promotion-review-1',
                'title': 'Promotion Review - Google',
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
        company = Company.objects.create(user=self.user, name='Google')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Backend Engineer',
            notes='Ask about platform ownership.',
        )
        other_company = Company.objects.create(user=self.other_user, name='Netflix')
        other_application = Application.objects.create(
            user=self.other_user,
            company=other_company,
            role_title='Hidden Role',
        )
        resume = Document.objects.create(
            user=self.user,
            application=application,
            title='Google Resume',
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
            title='Google JD Match',
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
            title='Google Cover Letter',
            payload={'applicationId': application.id, 'coverLetter': 'Dear Google...'},
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
        self.assertEqual(response.data['jd_reports'][0]['title'], 'Google JD Match')
        self.assertEqual(response.data['cover_letters'][0]['title'], 'Google Cover Letter')
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
                    'companyName': 'Google',
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
