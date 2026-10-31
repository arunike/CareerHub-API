from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, Company, Offer


class OfferPricePointsAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="price-points@example.com",
            email="price-points@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        company = Company.objects.create(user=self.user, name='Stripe')
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title='Software Engineer',
            status='OFFER',
        )
        self.offer = Offer.objects.create(
            application=application, base_salary=165000, equity_liquidity='BUYBACK'
        )

    def patch_points(self, points):
        return self.client.patch(
            f'/api/career/offers/{self.offer.id}/',
            {'equity_price_points': points},
            format='json',
        )

    def test_typed_prices_round_trip_through_a_second_request(self):
        """A write the serializer drops still returns 200, so it is read back separately."""
        points = [{'date': '2026-07-01', 'price': '125.00'}, {'date': '2026-10-01', 'price': 137.5}]
        self.assertEqual(self.patch_points(points).status_code, status.HTTP_200_OK)

        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertEqual(read.data['equity_price_points'], points)

    def test_a_grant_nobody_has_priced_is_an_empty_list(self):
        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertEqual(read.data['equity_price_points'], [])

    def test_clearing_every_price_is_a_write_of_its_own(self):
        self.patch_points([{'date': '2026-07-01', 'price': '125.00'}])
        self.assertEqual(self.patch_points([]).status_code, status.HTTP_200_OK)
        read = self.client.get(f'/api/career/offers/{self.offer.id}/')
        self.assertEqual(read.data['equity_price_points'], [])

    def test_a_shape_the_resolver_would_drop_is_rejected(self):
        for bad in (
            {'date': '2026-07-01'},
            {'date': 'July 2026', 'price': '125.00'},
            {'date': '2026-07-01', 'price': 0},
            {'date': '2026-07-01', 'price': -125},
            {'date': '2026-07-01', 'price': 'a hundred'},
            ['2026-07-01', 125],
        ):
            with self.subTest(bad=bad):
                self.assertEqual(
                    self.patch_points([bad]).status_code, status.HTTP_400_BAD_REQUEST
                )

        self.assertEqual(
            self.patch_points({'date': '2026-07-01', 'price': 125}).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_one_date_cannot_carry_two_prices(self):
        clash = [{'date': '2026-07-01', 'price': 125}, {'date': '2026-07-01', 'price': 137.5}]
        self.assertEqual(self.patch_points(clash).status_code, status.HTTP_400_BAD_REQUEST)
