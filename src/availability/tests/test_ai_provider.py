import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError


from django.contrib.auth import get_user_model
from django.test import override_settings
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


class AIProviderSettingsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='sanzhang',
            email='sanzhang@example.com',
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

    def test_current_settings_raises_validation_error_on_invalid_endpoint(self):
        response = self.client.put(
            self.current_settings_url,
            {
                'ai_provider_endpoint': 'ftp://api.example.com',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ai_provider_endpoint', response.data)


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

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_supports_custom_openai_compatible_endpoint(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_adapter = 'custom'
        settings.ai_provider_endpoint = 'https://api.mistral.ai/v1/chat/completions'
        settings.ai_provider_model = 'mistral-medium-latest'
        settings.set_ai_provider_api_key('mistral-key-1234')
        settings.save()

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {'choices': [{'message': {'content': 'Hello from Mistral'}}]}
        ).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Say hello'}], 'temperature': 0.4},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['choices'][0]['message']['content'],
            'Hello from Mistral',
        )
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://api.mistral.ai/v1/chat/completions')
        self.assertEqual(request.headers['Authorization'], 'Bearer mistral-key-1234')
        request_payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(request_payload['model'], 'mistral-medium-latest')
        self.assertEqual(request_payload['messages'], [{'role': 'user', 'content': 'Say hello'}])
        self.assertEqual(request_payload['temperature'], 0.4)

    def test_ai_provider_relay_requires_saved_provider_key(self):
        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('AI provider is not configured', response.data['detail'])

    @patch('availability.ai_provider.urlopen')
    @override_settings(AI_PROVIDER_REQUEST_TIMEOUT_SECONDS=60)
    def test_ai_provider_relay_keeps_timeout_below_platform_deadline(self, mock_urlopen):
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
            {'messages': [{'role': 'user', 'content': 'Say hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_urlopen.call_args.kwargs['timeout'], 55)

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_handles_timeout(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_adapter = 'openai'
        settings.ai_provider_endpoint = 'https://api.openai.com/v1/chat/completions'
        settings.ai_provider_model = 'gpt-test'
        settings.set_ai_provider_api_key('secret-key-1234')
        settings.save()

        mock_urlopen.side_effect = TimeoutError("The read operation timed out")

        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Say hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn('AI provider request timed out', response.data['detail'])

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_heals_invalid_json_with_newlines(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_adapter = 'openai'
        settings.ai_provider_endpoint = 'https://api.openai.com/v1/chat/completions'
        settings.ai_provider_model = 'gpt-test'
        settings.set_ai_provider_api_key('secret-key-1234')
        settings.save()

        invalid_json_content = '{\n  "how_to_strengthen": "**Critical gap**. Start with:\\n        1. Mentorship"\n}'
        # Wait, inside the python string, to simulate a raw unescaped newline, we should put an actual literal newline character inside the value:
        raw_newline_json = '{\n  "how_to_strengthen": "**Critical gap**. Start with:\n        1. Mentorship"\n}'

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {'choices': [{'message': {'content': raw_newline_json}}]}
        ).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Say hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = response.data['choices'][0]['message']['content']
        parsed = json.loads(content)
        self.assertEqual(parsed['how_to_strengthen'], '**Critical gap**. Start with:\n        1. Mentorship')

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_heals_invalid_json_with_array_colons(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_adapter = 'openai'
        settings.ai_provider_endpoint = 'https://api.openai.com/v1/chat/completions'
        settings.ai_provider_model = 'gpt-test'
        settings.set_ai_provider_api_key('secret-key-1234')
        settings.save()

        malformed_json = (
            '{\n'
            '  "strongest_evidence": [\n'
            '    "**Impact**": "$9.1M/month cost savings",\n'
            '    "**Ownership**": End-to-end delivery"\n'
            '  ]\n'
            '}'
        )

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {'choices': [{'message': {'content': malformed_json}}]}
        ).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Say hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = response.data['choices'][0]['message']['content']
        parsed = json.loads(content)
        self.assertEqual(
            parsed['strongest_evidence'],
            [
                '**Impact**: $9.1M/month cost savings',
                '**Ownership**: End-to-end delivery'
            ]
        )

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_heals_smart_quotes_and_trailing_bold_quotes(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_adapter = 'openai'
        settings.ai_provider_endpoint = 'https://api.openai.com/v1/chat/completions'
        settings.ai_provider_model = 'gpt-test'
        settings.set_ai_provider_api_key('secret-key-1234')
        settings.save()

        # Malformed JSON containing **“smart quotes, **” and trailing bold quotes "**
        malformed_json = (
            '{\n'
            '  "avoid_saying": [\n'
            '    **“smart quote here”**,\n'
            '    **”another one**”,\n'
            '    "trailing bold"**\n'
            '  ]\n'
            '}'
        )

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {'choices': [{'message': {'content': malformed_json}}]}
        ).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Say hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = response.data['choices'][0]['message']['content']
        parsed = json.loads(content)
        self.assertEqual(
            parsed['avoid_saying'],
            [
                '**smart quote here**',
                '**another one**',
                'trailing bold**'
            ]
        )

    @patch('availability.ai_provider.urlopen')
    def test_ai_provider_relay_surfaces_nested_provider_error_details(self, mock_urlopen):
        settings, _ = UserSettings.objects.get_or_create(user=self.user)
        settings.ai_provider_adapter = 'gemini'
        settings.ai_provider_endpoint = 'https://generativelanguage.googleapis.com/v1beta'
        settings.ai_provider_model = 'gemini-3-flash-preview'
        settings.set_ai_provider_api_key('google-key-1234')
        settings.save()

        error_body = json.dumps(
            {
                'error': {
                    'code': 400,
                    'status': 'INVALID_ARGUMENT',
                    'details': [
                        {
                            'reason': 'MODEL_NOT_SUPPORTED',
                            'domain': 'googleapis.com',
                        }
                    ],
                }
            }
        ).encode('utf-8')
        mock_urlopen.side_effect = HTTPError(
            url='https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent',
            code=400,
            msg='Bad Request',
            hdrs={},
            fp=BytesIO(error_body),
        )

        response = self.client.post(
            self.chat_completion_url,
            {'messages': [{'role': 'user', 'content': 'Say hello'}]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn('INVALID_ARGUMENT', response.data['detail'])
        self.assertIn('MODEL_NOT_SUPPORTED', response.data['detail'])


class JSONHealingTests(APITestCase):
    def test_try_heal_json_valid_json(self):
        from availability.ai_provider import try_heal_json
        valid_json = '{"a": 1, "b": [1, 2], "c": {"d": "hello"}}'
        self.assertEqual(json.loads(try_heal_json(valid_json)), json.loads(valid_json))

    def test_try_heal_json_flat_array_colons(self):
        from availability.ai_provider import try_heal_json
        malformed_json = '{"strongest_evidence": ["**Impact**": "Drove savings", "**Ownership**": "End-to-end"]}'
        expected_json = '{"strongest_evidence": ["**Impact**: Drove savings", "**Ownership**: End-to-end"]}'
        self.assertEqual(json.loads(try_heal_json(malformed_json)), json.loads(expected_json))

    def test_try_heal_json_unescaped_newlines(self):
        from availability.ai_provider import try_heal_json
        malformed_json = '{"draft": "Hello\nWorld"}'
        expected_json = '{"draft": "Hello\\nWorld"}'
        self.assertEqual(json.loads(try_heal_json(malformed_json)), json.loads(expected_json))

    def test_try_heal_json_unmatched_brackets(self):
        from availability.ai_provider import try_heal_json
        malformed_json = '{"draft_message": "Hello [Your Name]"\n    ]}'
        expected_json = '{"draft_message": "Hello [Your Name]"}'
        self.assertEqual(json.loads(try_heal_json(malformed_json)), json.loads(expected_json))

    def test_try_heal_json_brackets_in_string_literal(self):
        from availability.ai_provider import try_heal_json
        malformed_json = '{"evidence": ["**[Impact]**": "value1"], "nested": "[bracket]"}'
        expected_json = '{"evidence": ["**[Impact]**: value1"], "nested": "[bracket]"}'
        self.assertEqual(json.loads(try_heal_json(malformed_json)), json.loads(expected_json))

    def test_try_heal_json_yaml_block_scalar(self):
        from availability.ai_provider import try_heal_json
        malformed_json = '{"draft_message": >\n  Line 1\n  Line 2\n}'
        expected_json = '{"draft_message": "Line 1\\nLine 2"}'
        self.assertEqual(json.loads(try_heal_json(malformed_json)), json.loads(expected_json))

    def test_try_heal_json_array_bold_quotes(self):
        from availability.ai_provider import try_heal_json
        malformed_json = '{"avoid": [\n  **"‘I think.’** (direct)",\n  **"Assumptions** (ask)"\n]}'
        expected_json = '{"avoid": [\n  "**‘I think.’** (direct)",\n  "**Assumptions** (ask)"\n]}'
        self.assertEqual(json.loads(try_heal_json(malformed_json)), json.loads(expected_json))
