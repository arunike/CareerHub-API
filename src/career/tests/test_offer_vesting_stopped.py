from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, Company, Offer


class OfferVestingStoppedAPITests(APITestCase):
    """The day a grant stopped vesting, recorded against the offer rather than the role."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="vesting-stopped@example.com",
            email="vesting-stopped@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        company = Company.objects.create(user=self.user, name='Google')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='OFFER',
        )
        self.offer = Offer.objects.create(application=application, base_salary=165000)

    def patch_stopped(self, value):
        return self.client.patch(
            f'/api/career/offers/{self.offer.id}/',
            {'equity_vesting_stopped_on': value},
            format='json',
        )

    def test_a_grant_still_vesting_has_no_stop_date(self):
        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertIsNone(read.data['equity_vesting_stopped_on'])

    def test_the_stop_date_round_trips(self):
        self.assertEqual(self.patch_stopped('2026-11-01').status_code, status.HTTP_200_OK)
        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertEqual(read.data['equity_vesting_stopped_on'], '2026-11-01')

    def test_clearing_the_stop_date_restarts_the_schedule(self):
        self.patch_stopped('2026-11-01')
        self.assertEqual(self.patch_stopped(None).status_code, status.HTTP_200_OK)
        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertIsNone(read.data['equity_vesting_stopped_on'])

    def test_a_day_that_is_not_a_date_is_rejected(self):
        response = self.patch_stopped('the day I left')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('equity_vesting_stopped_on', response.data)
