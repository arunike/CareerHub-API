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
        settings.ai_provider_adapter = 'openai'
        settings.ai_provider_endpoint = 'https://api.openai.com/v1/chat/completions'
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

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_supports_gemini_native(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_adapter = 'gemini'
        settings.ai_provider_endpoint = 'https://generativelanguage.googleapis.com/v1beta'
        settings.ai_provider_model = 'gemini-3-flash-preview'
        settings.set_ai_provider_api_key('google-key-1234')
        settings.save()

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                'candidates': [
                    {
                        'content': {
                            'parts': [{'text': 'Hello from Gemini native'}],
                        }
                    }
                ]
            }
        ).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        response = self.client.post(
            self.chat_completion_url,
            {
                'messages': [
                    {'role': 'system', 'content': 'Be brief'},
                    {'role': 'user', 'content': 'Say hello'},
                ],
                'temperature': 0.3,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['choices'][0]['message']['content'],
            'Hello from Gemini native',
        )
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(
            request.full_url,
            'https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent',
        )
        self.assertEqual(request.headers['X-goog-api-key'], 'google-key-1234')

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_supports_claude_messages(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_adapter = 'claude'
        settings.ai_provider_endpoint = 'https://api.anthropic.com'
        settings.ai_provider_model = 'claude-sonnet-4-20250514'
        settings.set_ai_provider_api_key('claude-key-1234')
        settings.save()

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                'content': [{'type': 'text', 'text': 'Hello from Claude'}],
                'model': 'claude-sonnet-4-20250514',
                'role': 'assistant',
                'type': 'message',
            }
        ).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        response = self.client.post(
            self.chat_completion_url,
            {
                'messages': [
                    {'role': 'system', 'content': 'Be brief'},
                    {'role': 'user', 'content': 'Say hello'},
                ],
                'temperature': 0.3,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['choices'][0]['message']['content'],
            'Hello from Claude',
        )
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://api.anthropic.com/v1/messages')
        self.assertEqual(request.headers['X-api-key'], 'claude-key-1234')
        self.assertEqual(request.headers['Anthropic-version'], '2023-06-01')

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_supports_openrouter(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_adapter = 'openrouter'
        settings.ai_provider_endpoint = 'https://openrouter.ai/api/v1/chat/completions'
        settings.ai_provider_model = 'openai/gpt-5.2'
        settings.set_ai_provider_api_key('openrouter-key-1234')
        settings.save()

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {'choices': [{'message': {'content': 'Hello from OpenRouter'}}]}
        ).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Say hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['choices'][0]['message']['content'],
            'Hello from OpenRouter',
        )
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(request.headers['Authorization'], 'Bearer openrouter-key-1234')
        self.assertEqual(request.headers['X-openrouter-title'], 'CareerHub')

    def test_ai_provider_relay_requires_saved_provider_key(self):
        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('AI provider is not configured', response.data['detail'])


class AuthJwtFlowTests(APITestCase):
    def setUp(self):
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
