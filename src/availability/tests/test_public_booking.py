import json
from io import BytesIO
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from django.core.cache import cache
from django.core import mail
from decimal import Decimal

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
            host_display_name='San Zhang',
            host_email='sanzhang@example.com',
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
                'intake_answers': {'company': 'Google'},
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
                'intake_answers': {'company': 'Google'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        booking = PublicBooking.objects.get()
        self.assertEqual(booking.intake_answers['company'], 'Google')
        self.assertTrue(booking.event.is_locked)
        self.assertIn('Google', booking.event.notes)
        self.assertIn('reschedule_url', response.data['booking'])
        self.assertTrue(
            response.data['booking']['reschedule_url'].startswith('https://careerhub-frontend.vercel.app/book/')
        )
        self.assertTrue(response.data['booking']['ics_url'].startswith('http://testserver/api/booking/'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['sanzhang@example.com'])
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
                'intake_answers': {'company': 'Google'},
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
                'intake_answers': {'company': 'Google'},
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
                'intake_answers': {'company': 'Google'},
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
                'intake_answers': {'company': 'Google'},
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
                'intake_answers': {'company': 'Google'},
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
