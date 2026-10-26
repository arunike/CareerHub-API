from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, Company, Offer


class OfferVestOverridesAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="vest-overrides@example.com",
            email="vest-overrides@example.com",
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

    def patch_overrides(self, overrides):
        return self.client.patch(
            f'/api/career/offers/{self.offer.id}/',
            {'equity_vest_overrides': overrides},
            format='json',
        )

    def test_moved_dates_round_trip_through_a_second_request(self):
        """A write the serializer drops still returns 200, so it is read back separately."""
        moved = [{'months': 12, 'date': '2026-07-01'}, {'months': 24, 'date': '2027-10-01'}]
        self.assertEqual(self.patch_overrides(moved).status_code, status.HTTP_200_OK)

        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertEqual(read.data['equity_vest_overrides'], moved)

    def test_an_untouched_schedule_is_an_empty_list(self):
        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertEqual(read.data['equity_vest_overrides'], [])

    def test_clearing_every_move_is_a_write_of_its_own(self):
        self.patch_overrides([{'months': 12, 'date': '2026-07-01'}])
        self.assertEqual(self.patch_overrides([]).status_code, status.HTTP_200_OK)
        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertEqual(read.data['equity_vest_overrides'], [])

    def test_a_shape_the_resolver_would_drop_is_rejected(self):
        for bad in (
            {'months': 12},
            {'months': 12, 'date': 'July 2026'},
            {'months': -12, 'date': '2026-07-01'},
            {'months': 'twelve', 'date': '2026-07-01'},
            ['months', 12],
        ):
            with self.subTest(bad=bad):
                response = self.patch_overrides([bad])
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(self.patch_overrides({'months': 12}).status_code, status.HTTP_400_BAD_REQUEST)
