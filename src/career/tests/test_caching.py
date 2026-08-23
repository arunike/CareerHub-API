
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import AIArtifact, Application, Company, Offer


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
        from ..models import Task
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
        from ..cache import get_applications_cache_key

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
