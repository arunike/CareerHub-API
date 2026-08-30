from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase


class HiddenIncomeSettingsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='hidden-income@example.com',
            email='hidden-income@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_authenticate(self.user)
        self.url = '/api/user-settings/current/'

    def test_defaults_to_hiding_nothing(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['hidden_income_roles'], [])
        self.assertEqual(response.data['hidden_income_years'], [])

    def test_hidden_roles_round_trip_to_another_session(self):
        saved = self.client.put(
            self.url, {'hidden_income_roles': ['experience-2']}, format='json'
        )
        self.assertEqual(saved.status_code, 200)
        # Read back through a second request: a 200 alone does not prove it persisted.
        self.assertEqual(
            self.client.get(self.url).data['hidden_income_roles'], ['experience-2']
        )

    def test_hidden_years_round_trip(self):
        self.client.put(self.url, {'hidden_income_years': [2022, 2023]}, format='json')
        self.assertEqual(self.client.get(self.url).data['hidden_income_years'], [2022, 2023])

    def test_the_two_lists_are_independent(self):
        self.client.put(self.url, {'hidden_income_roles': ['offer-1']}, format='json')
        self.client.put(self.url, {'hidden_income_years': [2024]}, format='json')
        current = self.client.get(self.url).data
        self.assertEqual(current['hidden_income_roles'], ['offer-1'])
        self.assertEqual(current['hidden_income_years'], [2024])

    def test_clearing_a_list_is_saved(self):
        self.client.put(self.url, {'hidden_income_roles': ['offer-1']}, format='json')
        self.client.put(self.url, {'hidden_income_roles': []}, format='json')
        self.assertEqual(self.client.get(self.url).data['hidden_income_roles'], [])

    def test_another_user_sees_their_own_settings(self):
        self.client.put(self.url, {'hidden_income_years': [2021]}, format='json')
        other = get_user_model().objects.create_user(
            username='other-income@example.com',
            email='other-income@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(self.url).data['hidden_income_years'], [])
