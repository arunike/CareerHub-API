import json
from io import BytesIO
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from django.core.cache import cache
from django.core import mail
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from availability.models import Event, PublicBooking, ShareLink, UserSettings


def available_9_to_10(dates, timezone_code, user=None):
    return {
        item.strftime('%Y-%m-%d'): {
            'date': item.strftime('%Y-%m-%d'),
            'availability': '9:00 AM - 10:00 AM',
        }
        for item in dates
    }


class AvailabilityRangeTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='availability-host',
            email='availability@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)

    @patch('availability.views.availability.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_generate_defaults_to_two_weeks(self, _mock_availability):
        response = self.client.get('/api/availability/generate/?start_date=2026-05-04')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 14)

    @patch('availability.views.availability.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_generate_uses_saved_or_requested_week_range(self, _mock_availability):
        UserSettings.objects.create(user=self.user, availability_weeks=16)

        saved_response = self.client.get('/api/availability/generate/?start_date=2026-05-04')
        requested_response = self.client.get('/api/availability/generate/?start_date=2026-05-04&weeks=1')

        self.assertEqual(saved_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(saved_response.data), 112)
        self.assertEqual(requested_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(requested_response.data), 7)

    @patch(
        'availability.utils.timezone.now',
        return_value=datetime(2026, 6, 3, 19, 0, tzinfo=dt_timezone.utc),
    )
    def test_generate_hides_elapsed_time_blocks_for_today(self, _mock_now):
        UserSettings.objects.create(
            user=self.user,
            work_time_ranges=[
                {'start': '11:00:00', 'end': '12:00:00'},
                {'start': '14:00:00', 'end': '17:00:00'},
            ],
        )

        response = self.client.get(
            '/api/availability/generate/?start_date=2026-06-03&weeks=1&timezone=America/Los_Angeles'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        today = next(item for item in response.data if item['date'] == '2026-06-03')
        self.assertEqual(today['availability'], '2:00 PM - 5:00 PM')


    @patch(
        'availability.utils.timezone.now',
        return_value=datetime(2026, 6, 4, 1, 57, tzinfo=dt_timezone.utc),
    )
    def test_generate_hides_today_when_all_time_blocks_elapsed(self, _mock_now):
        UserSettings.objects.create(
            user=self.user,
            work_time_ranges=[
                {'start': '11:00:00', 'end': '12:00:00'},
                {'start': '14:00:00', 'end': '17:00:00'},
            ],
        )

        response = self.client.get(
            '/api/availability/generate/?start_date=2026-06-03&weeks=1&timezone=America/Los_Angeles'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('2026-06-03', [item['date'] for item in response.data])


class EventFeedPaginationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username='event-feed-user',
            email='event-feed@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)

    def test_feed_paginates_all_regular_events_without_a_fixed_date_window(self):
        Event.objects.create(
            user=self.user,
            name='Old event',
            date='2024-01-10',
            start_time='09:00:00',
            end_time='10:00:00',
        )
        Event.objects.create(
            user=self.user,
            name='Middle event',
            date='2025-01-10',
            start_time='09:00:00',
            end_time='10:00:00',
        )
        Event.objects.create(
            user=self.user,
            name='Future event',
            date='2027-01-10',
            start_time='09:00:00',
            end_time='10:00:00',
        )

        response = self.client.get(
            '/api/events/feed/',
            {'page': 2, 'page_size': 2, 'year': 'all', 'sort_order': 'asc'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual([item['name'] for item in response.data['results']], ['Future event'])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PublicBookingEnhancementTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='booking-host',
            email='host-account@example.com',
            password='test-pass-123',
        )
        self.link = ShareLink.objects.create(
            user=self.user,
            uuid='public-link-1',
            title='Recruiter screen',
            host_display_name='Richie',
            host_email='host@example.com',
            duration_days=14,
            booking_block_minutes=30,
            buffer_minutes=0,
            max_bookings_per_day=0,
            expires_at=timezone.now() + timedelta(days=14),
            intake_questions=[
                {'id': 'company', 'label': 'Company', 'required': True},
                {'id': 'agenda', 'label': 'Agenda', 'required': False},
            ],
        )

    @patch('availability.views.booking.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_booking_requires_required_intake_answers(self, _mock_availability):
        response = self.client.post(
            f'/api/booking/{self.link.uuid}/book/',
            {
                'name': 'Recruiter',
                'email': 'recruiter@example.com',
                'date': timezone.now().date().strftime('%Y-%m-%d'),
                'start_time': '09:00:00',
                'end_time': '09:30:00',
                'timezone': 'America/Los_Angeles',
                'intake_answers': {},
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Company is required', response.data['error'])

    @patch('availability.views.booking.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_booking_rejects_invalid_guest_email(self, _mock_availability):
        response = self.client.post(
            f'/api/booking/{self.link.uuid}/book/',
            {
                'name': 'Recruiter',
                'email': 'fdjfosjkfo',
                'date': timezone.now().date().strftime('%Y-%m-%d'),
                'start_time': '09:00:00',
                'end_time': '09:30:00',
                'timezone': 'America/Los_Angeles',
                'intake_answers': {'company': 'Acme'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('valid email', response.data['error'])
        self.assertEqual(PublicBooking.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)

    @patch('availability.views.booking.calculate_availability_for_dates', side_effect=available_9_to_10)
    @override_settings(PUBLIC_FRONTEND_BASE_URL='https://careerhub-frontend.vercel.app')
    def test_booking_creates_locked_event_and_host_email_with_ics(self, _mock_availability):
        response = self.client.post(
            f'/api/booking/{self.link.uuid}/book/',
            {
                'name': 'Recruiter',
                'email': 'recruiter@example.com',
                'date': timezone.now().date().strftime('%Y-%m-%d'),
                'start_time': '09:00:00',
                'end_time': '09:30:00',
                'timezone': 'America/Los_Angeles',
                'notes': 'Bring role details.',
                'intake_answers': {'company': 'Acme'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        booking = PublicBooking.objects.get()
        self.assertEqual(booking.intake_answers['company'], 'Acme')
        self.assertTrue(booking.event.is_locked)
        self.assertIn('Acme', booking.event.notes)
        self.assertIn('reschedule_url', response.data['booking'])
        self.assertTrue(
            response.data['booking']['reschedule_url'].startswith('https://careerhub-frontend.vercel.app/book/')
        )
        self.assertTrue(response.data['booking']['ics_url'].startswith('http://testserver/api/booking/'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['host@example.com'])
        self.assertEqual(mail.outbox[0].attachments[0][2], 'text/calendar')
        self.assertIn('https://careerhub-frontend.vercel.app/book/', mail.outbox[0].body)

    @patch('availability.views.booking.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_booking_slots_use_visitor_iana_timezone_date(self, _mock_availability):
        response = self.client.get(
            f'/api/booking/{self.link.uuid}/slots/',
            {'date': '2026-05-02', 'days': 1, 'timezone': 'Asia/Tokyo'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['timezone'], 'Asia/Tokyo')
        self.assertEqual(response.data['days'][0]['date'], '2026-05-02')
        self.assertEqual(response.data['days'][0]['slots'][0]['start_time'], '01:00:00')

    @patch('availability.views.booking.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_cancel_marks_booking_canceled_and_removes_locked_event(self, _mock_availability):
        create_response = self.client.post(
            f'/api/booking/{self.link.uuid}/book/',
            {
                'name': 'Recruiter',
                'email': 'recruiter@example.com',
                'date': timezone.now().date().strftime('%Y-%m-%d'),
                'start_time': '09:00:00',
                'end_time': '09:30:00',
                'timezone': 'America/Los_Angeles',
                'intake_answers': {'company': 'Acme'},
            },
            format='json',
        )
        booking_uuid = create_response.data['booking']['uuid']
        event_id = PublicBooking.objects.get(uuid=booking_uuid).event_id

        response = self.client.post(
            f'/api/booking/{self.link.uuid}/manage/{booking_uuid}/cancel/',
            {'cancel_reason': 'The role was put on hold.'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking = PublicBooking.objects.get(uuid=booking_uuid)
        self.assertEqual(booking.status, PublicBooking.STATUS_CANCELED)
        self.assertEqual(booking.cancel_reason, 'The role was put on hold.')
        self.assertFalse(Event.objects.filter(id=event_id).exists())
        self.assertIn('The role was put on hold.', mail.outbox[-1].body)

    @patch('availability.views.booking.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_change_deadline_blocks_late_public_cancel_and_reschedule(self, _mock_availability):
        self.link.reschedule_cancel_deadline_hours = 24
        self.link.save(update_fields=['reschedule_cancel_deadline_hours'])
        booking_date = (timezone.now() + timedelta(hours=12)).date()
        create_response = self.client.post(
            f'/api/booking/{self.link.uuid}/book/',
            {
                'name': 'Recruiter',
                'email': 'recruiter@example.com',
                'date': booking_date.strftime('%Y-%m-%d'),
                'start_time': '09:00:00',
                'end_time': '09:30:00',
                'timezone': 'America/Los_Angeles',
                'intake_answers': {'company': 'Acme'},
            },
            format='json',
        )
        booking_uuid = create_response.data['booking']['uuid']

        cancel_response = self.client.post(
            f'/api/booking/{self.link.uuid}/manage/{booking_uuid}/cancel/',
            {'cancel_reason': 'Need to move this.'},
            format='json',
        )
        reschedule_response = self.client.post(
            f'/api/booking/{self.link.uuid}/manage/{booking_uuid}/reschedule/',
            {
                'date': booking_date.strftime('%Y-%m-%d'),
                'start_time': '09:30:00',
                'end_time': '10:00:00',
                'timezone': 'America/Los_Angeles',
            },
            format='json',
        )

        self.assertEqual(cancel_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('24 hours', cancel_response.data['error'])
        self.assertEqual(reschedule_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(PublicBooking.objects.get(uuid=booking_uuid).status, PublicBooking.STATUS_ACTIVE)

    @patch('availability.views.booking.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_host_cancel_ignores_guest_change_deadline_and_removes_event(self, _mock_availability):
        self.link.reschedule_cancel_deadline_hours = 24
        self.link.save(update_fields=['reschedule_cancel_deadline_hours'])
        booking_date = (timezone.now() + timedelta(hours=12)).date()
        create_response = self.client.post(
            f'/api/booking/{self.link.uuid}/book/',
            {
                'name': 'Recruiter',
                'email': 'recruiter@example.com',
                'date': booking_date.strftime('%Y-%m-%d'),
                'start_time': '09:00:00',
                'end_time': '09:30:00',
                'timezone': 'America/Los_Angeles',
                'intake_answers': {'company': 'Acme'},
            },
            format='json',
        )
        booking = PublicBooking.objects.get(uuid=create_response.data['booking']['uuid'])
        event_id = booking.event_id

        self.client.force_login(self.user)
        response = self.client.post(
            f'/api/public-bookings/{booking.id}/cancel/',
            {'cancel_reason': 'Host canceled from booking manager.'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, PublicBooking.STATUS_CANCELED)
        self.assertEqual(booking.cancel_reason, 'Host canceled from booking manager.')
        self.assertFalse(Event.objects.filter(id=event_id).exists())
        self.assertEqual(response.data['booking']['status'], PublicBooking.STATUS_CANCELED)

    @patch('availability.views.booking.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_share_link_serializer_includes_booking_analytics(self, _mock_availability):
        self.client.force_login(self.user)
        active_response = self.client.post(
            f'/api/booking/{self.link.uuid}/book/',
            {
                'name': 'Recruiter',
                'email': 'recruiter@example.com',
                'date': timezone.now().date().strftime('%Y-%m-%d'),
                'start_time': '09:00:00',
                'end_time': '09:30:00',
                'timezone': 'America/Los_Angeles',
                'intake_answers': {'company': 'Acme'},
            },
            format='json',
        )
        canceled_response = self.client.post(
            f'/api/booking/{self.link.uuid}/book/',
            {
                'name': 'Coordinator',
                'email': 'coordinator@example.com',
                'date': timezone.now().date().strftime('%Y-%m-%d'),
                'start_time': '09:30:00',
                'end_time': '10:00:00',
                'timezone': 'America/Los_Angeles',
                'intake_answers': {'company': 'Beta'},
            },
            format='json',
        )
        self.client.post(
            f'/api/booking/{self.link.uuid}/manage/{canceled_response.data["booking"]["uuid"]}/cancel/',
            {'cancel_reason': 'Duplicate booking.'},
            format='json',
        )

        response = self.client.get('/api/share-links/')

        self.assertEqual(active_response.status_code, status.HTTP_201_CREATED)
        analytics = response.data[0]['booking_analytics']
        self.assertEqual(analytics['total'], 2)
        self.assertEqual(analytics['active'], 1)
        self.assertEqual(analytics['canceled'], 1)
        self.assertEqual(analytics['upcoming'], 1)

    @patch('availability.views.booking.calculate_availability_for_dates', side_effect=available_9_to_10)
    def test_reschedule_updates_booking_and_locked_event(self, _mock_availability):
        create_response = self.client.post(
            f'/api/booking/{self.link.uuid}/book/',
            {
                'name': 'Recruiter',
                'email': 'recruiter@example.com',
                'date': timezone.now().date().strftime('%Y-%m-%d'),
                'start_time': '09:00:00',
                'end_time': '09:30:00',
                'timezone': 'America/Los_Angeles',
                'intake_answers': {'company': 'Acme'},
            },
            format='json',
        )
        booking_uuid = create_response.data['booking']['uuid']

        response = self.client.post(
            f'/api/booking/{self.link.uuid}/manage/{booking_uuid}/reschedule/',
            {
                'date': timezone.now().date().strftime('%Y-%m-%d'),
                'start_time': '09:30:00',
                'end_time': '10:00:00',
                'timezone': 'America/Los_Angeles',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking = PublicBooking.objects.get(uuid=booking_uuid)
        self.assertEqual(booking.start_time, '09:30:00')
        self.assertEqual(booking.event.start_time, '09:30:00')


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


class HolidayCachingTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="holiday-cache-user",
            email="holiday-cache@example.com",
            password="test-pass-123",
        )
        self.client.force_login(self.user)

    def test_holiday_list_caching_and_invalidation(self):
        from django.core.cache import cache
        from availability.models import CustomHoliday
        
        holiday = CustomHoliday.objects.create(
            user=self.user,
            date="2026-12-25",
            description="Christmas",
            holiday_type="company",
        )
        
        response1 = self.client.get('/api/holidays/')
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response1.data), 1)
        
        CustomHoliday.objects.filter(id=holiday.id).update(description="Christmas Updated")
        
        response2 = self.client.get('/api/holidays/')
        self.assertEqual(response2.data[0]['description'], "Christmas")
        
        holiday.description = "Christmas Updated Save"
        holiday.save()
        
        response3 = self.client.get('/api/holidays/')
        self.assertEqual(response3.data[0]['description'], "Christmas Updated Save")

    def test_holiday_federal_caching_and_invalidation(self):
        from datetime import datetime
        from django.core.cache import cache
        from availability.models import CustomHoliday
        
        response1 = self.client.get('/api/holidays/federal/')
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        count_before = len(response1.data)
        
        holiday = CustomHoliday.objects.create(
            user=self.user,
            date=f"{datetime.now().year}-07-04",
            description="Custom July 4th",
            holiday_type="federal",
        )
        
        response2 = self.client.get('/api/holidays/federal/')
        self.assertEqual(len(response2.data), count_before + 1)


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
