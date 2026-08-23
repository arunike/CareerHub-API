import json

from django.core.cache import cache

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import UserSettings


def available_9_to_10(dates, timezone_code, user=None):
    return {
        item.strftime('%Y-%m-%d'): {
            'date': item.strftime('%Y-%m-%d'),
            'availability': '9:00 AM - 10:00 AM',
        }
        for item in dates
    }


class AuthJwtFlowTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username='jwt-user',
            email='jwt@example.com',
            password='test-pass-123',
        )
        self.login_url = '/api/auth/login/'
        self.refresh_url = '/api/auth/refresh/'
        self.me_url = '/api/auth/me/'

    def test_login_returns_access_and_refresh_tokens(self):
        response = self.client.post(
            self.login_url,
            {
                'email': 'jwt@example.com',
                'password': 'test-pass-123',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['user']['email'], 'jwt@example.com')

    def test_bearer_token_can_fetch_current_user(self):
        login_response = self.client.post(
            self.login_url,
            {
                'email': 'jwt@example.com',
                'password': 'test-pass-123',
            },
            format='json',
        )
        access_token = login_response.data['access']

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        me_response = self.client.get(self.me_url)

        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data['user']['email'], 'jwt@example.com')

    def test_refresh_endpoint_rotates_access_token(self):
        login_response = self.client.post(
            self.login_url,
            {
                'email': 'jwt@example.com',
                'password': 'test-pass-123',
            },
            format='json',
        )

        refresh_response = self.client.post(
            self.refresh_url,
            {'refresh': login_response.data['refresh']},
            format='json',
        )

        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh_response.data)
        self.assertIn('refresh', refresh_response.data)
        self.assertNotEqual(refresh_response.data['refresh'], login_response.data['refresh'])

        reused_refresh_response = self.client.post(
            self.refresh_url,
            {'refresh': login_response.data['refresh']},
            format='json',
        )

        self.assertEqual(reused_refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_refresh_token(self):
        login_response = self.client.post(
            self.login_url,
            {
                'email': 'jwt@example.com',
                'password': 'test-pass-123',
            },
            format='json',
        )

        logout_response = self.client.post(
            '/api/auth/logout/',
            {'refresh': login_response.data['refresh']},
            format='json',
        )
        self.assertEqual(logout_response.status_code, status.HTTP_204_NO_CONTENT)

        refresh_response = self.client.post(
            self.refresh_url,
            {'refresh': login_response.data['refresh']},
            format='json',
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pending_account_deletion_blocks_existing_access_token(self):
        login_response = self.client.post(
            self.login_url,
            {
                'email': 'jwt@example.com',
                'password': 'test-pass-123',
            },
            format='json',
        )
        user_settings, _ = UserSettings.objects.get_or_create(user=self.user)
        user_settings.schedule_account_deletion()
        user_settings.save()

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}")
        me_response = self.client.get(self.me_url)

        self.assertEqual(me_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pending_account_deletion_blocks_refresh_token(self):
        login_response = self.client.post(
            self.login_url,
            {
                'email': 'jwt@example.com',
                'password': 'test-pass-123',
            },
            format='json',
        )
        user_settings, _ = UserSettings.objects.get_or_create(user=self.user)
        user_settings.schedule_account_deletion()
        user_settings.save()

        refresh_response = self.client.post(
            self.refresh_url,
            {'refresh': login_response.data['refresh']},
            format='json',
        )

        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pending_account_deletion_blocks_existing_session(self):
        self.client.force_login(self.user)
        user_settings, _ = UserSettings.objects.get_or_create(user=self.user)
        user_settings.schedule_account_deletion()
        user_settings.save()

        refresh_response = self.client.post(
            self.refresh_url,
            {'refresh': login_response.data['refresh']},
            format='json',
        )

        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pending_account_deletion_blocks_existing_session(self):
        self.client.force_login(self.user)
        user_settings, _ = UserSettings.objects.get_or_create(user=self.user)
        user_settings.schedule_account_deletion()
        user_settings.save()

        me_response = self.client.get(self.me_url)

        self.assertEqual(me_response.status_code, status.HTTP_401_UNAUTHORIZED)
