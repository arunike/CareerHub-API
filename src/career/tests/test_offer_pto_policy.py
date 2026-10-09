from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, Company, Offer


class OfferPtoPolicyAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pto-policy@example.com",
            email="pto-policy@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        company = Company.objects.create(user=self.user, name='Google')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer III',
            status='OFFER',
        )
        self.offer = Offer.objects.create(application=application, base_salary=165000)

    def test_lapse_month_round_trips_through_a_second_request(self):
        """A write that the serializer drops still returns 200, so it is read back separately."""
        patch = self.client.patch(
            f'/api/career/offers/{self.offer.id}/',
            {'pto_rollover_expires_month': 4},
            format='json',
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK)

        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertEqual(read.data['pto_rollover_expires_month'], 4)

    def test_never_lapsing_is_the_default(self):
        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertEqual(read.data['pto_rollover_expires_month'], 0)
