import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, Company, Experience, Offer
from ..services.offers import calculate_realizable_equity


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
                'company_name': 'Google',
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
        self.assertEqual(offers_response.data[0]['application_details']['company'], 'Google')

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
