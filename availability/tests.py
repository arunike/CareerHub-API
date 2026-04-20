import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import UserSettings


class AIProviderSettingsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='richie',
            email='richie@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)
        self.current_settings_url = '/api/user-settings/current/'
        self.chat_completion_url = '/api/user-settings/ai-provider/chat-completions/'

    def test_current_settings_encrypts_api_key_without_echoing_plaintext(self):
        response = self.client.put(
            self.current_settings_url,
            {
                'ai_provider_endpoint': 'https://api.example.com/v1/chat/completions',
                'ai_provider_model': 'gpt-test',
                'ai_provider_api_key': 'secret-key-1234',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('ai_provider_api_key', response.data)
        self.assertTrue(response.data['ai_provider_api_key_configured'])
        self.assertEqual(response.data['ai_provider_api_key_masked'], '••••••••1234')

        settings = UserSettings.objects.get(user=self.user)
        self.assertNotEqual(settings.ai_provider_api_key_encrypted, 'secret-key-1234')
        self.assertEqual(settings.get_ai_provider_api_key(), 'secret-key-1234')

    def test_current_settings_can_clear_stored_api_key(self):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.set_ai_provider_api_key('secret-key-1234')
        settings.save(update_fields=['ai_provider_api_key_encrypted'])

        response = self.client.put(
            self.current_settings_url,
            {'ai_provider_api_key': ''},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['ai_provider_api_key_configured'])
        self.assertEqual(response.data['ai_provider_api_key_masked'], '')

        settings.refresh_from_db()
        self.assertEqual(settings.ai_provider_api_key_encrypted, '')

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_uses_stored_secret(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_endpoint = 'https://api.example.com/v1/chat/completions'
        settings.ai_provider_model = 'gpt-test'
        settings.set_ai_provider_api_key('secret-key-1234')
        settings.save()

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {'choices': [{'message': {'content': 'Hello from provider'}}]}
        ).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        response = self.client.post(
            self.chat_completion_url,
            {
                'messages': [{'role': 'user', 'content': 'Say hello'}],
                'temperature': 0.3,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['choices'][0]['message']['content'],
            'Hello from provider',
        )
        self.assertTrue(mock_urlopen.called)

    def test_ai_provider_relay_requires_saved_provider_key(self):
        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('AI provider is not configured', response.data['detail'])
