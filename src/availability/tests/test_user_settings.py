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


class UserSettingsNavigationTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='sanzhang',
            email='sanzhang@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)
        self.current_settings_url = '/api/user-settings/current/'

    def test_current_settings_saves_mobile_toolbar_items_in_order(self):
        toolbar_items = ['/applications', '__smart__', '/tasks', '/analytics']

        response = self.client.put(
            self.current_settings_url,
            {'mobile_toolbar_items': toolbar_items},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['mobile_toolbar_items'], toolbar_items)
        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.mobile_toolbar_items, toolbar_items)

    def test_current_settings_rejects_invalid_mobile_toolbar_items(self):
        invalid_values = [
            ['/applications'] * 5,
            ['/applications', '/applications'],
            ['/not-a-page'],
        ]

        for toolbar_items in invalid_values:
            with self.subTest(toolbar_items=toolbar_items):
                response = self.client.put(
                    self.current_settings_url,
                    {'mobile_toolbar_items': toolbar_items},
                    format='json',
                )

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn('mobile_toolbar_items', response.data)


class AccountBackedLayoutSettingsTests(APITestCase):
    """Widgets and hand-arranged layouts used to live only in localStorage, invisible on a phone."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='chriswong',
            email='chriswong@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_login(self.user)
        self.url = '/api/user-settings/current/'

    def test_defaults_are_empty_rather_than_null(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['custom_analytics_widgets'], [])
        self.assertEqual(response.data['analytics_widget_order'], {})
        self.assertEqual(response.data['analytics_widgets_enabled'], {})
        self.assertEqual(response.data['contact_network_positions'], {})

    def test_saves_authored_analytics_widgets(self):
        widgets = [
            {
                'id': 'custom-1',
                'name': 'Offers per month',
                'query': 'count offers by month',
                'widgetType': 'chart',
                'icon': 'BarChartOutlined',
                'color': 'blue',
                'createdAt': '2026-07-01T00:00:00.000Z',
                'queryType': 'ai',
            }
        ]

        response = self.client.put(self.url, {'custom_analytics_widgets': widgets}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.custom_analytics_widgets[0]['name'], 'Offers per month')

    def test_dashboard_layout_is_keyed_per_dashboard(self):
        response = self.client.put(
            self.url,
            {
                'analytics_widget_order': {
                    'jobHunt': ['funnel', 'response'],
                    'availability': ['booked'],
                },
                'analytics_widgets_enabled': {'jobHunt': ['funnel']},
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.analytics_widget_order['jobHunt'], ['funnel', 'response'])
        self.assertEqual(settings.analytics_widget_order['availability'], ['booked'])

    def test_saving_one_dashboard_leaves_the_other_alone(self):
        self.client.put(
            self.url,
            {'analytics_widget_order': {'jobHunt': ['funnel'], 'availability': ['booked']}},
            format='json',
        )
        # The client merges, so a second dashboard's save carries both keys.
        self.client.put(
            self.url,
            {'analytics_widget_order': {'jobHunt': ['funnel'], 'availability': ['booked', 'gaps']}},
            format='json',
        )

        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.analytics_widget_order['jobHunt'], ['funnel'])
        self.assertEqual(settings.analytics_widget_order['availability'], ['booked', 'gaps'])

    def test_saves_contact_graph_layout(self):
        layout = {'nodes': {'me:0': {'x': 120, 'y': 240}}, 'labels': {'0:4': 0.42}}

        response = self.client.put(self.url, {'contact_network_positions': layout}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.contact_network_positions['nodes']['me:0']['x'], 120)
        self.assertEqual(settings.contact_network_positions['labels']['0:4'], 0.42)

    def test_a_partial_save_does_not_wipe_the_other_fields(self):
        self.client.put(self.url, {'custom_analytics_widgets': [{'id': 'a'}]}, format='json')
        self.client.put(self.url, {'contact_network_positions': {'nodes': {}}}, format='json')

        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.custom_analytics_widgets, [{'id': 'a'}])

    def test_another_user_does_not_see_them(self):
        self.client.put(self.url, {'custom_analytics_widgets': [{'id': 'a'}]}, format='json')
        other = get_user_model().objects.create_user(
            username='johnsmith',
            email='johnsmith@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url).data['custom_analytics_widgets'], [])


class DrivingDefaultsSettingsTests(APITestCase):
    """MPG and pump price belong to the person, not to one offer, so they live here and."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='chriswong',
            email='chriswong@example.com',
            password='test-pass-123',
        )
        self.client.force_login(self.user)
        self.current_settings_url = '/api/user-settings/current/'

    def test_current_settings_exposes_driving_defaults(self):
        response = self.client.get(self.current_settings_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Present from the start, so the first offer priced by fuel has figures to use.
        self.assertEqual(Decimal(str(response.data['default_mpg'])), Decimal('28'))
        self.assertEqual(
            Decimal(str(response.data['default_gas_price_per_gallon'])), Decimal('4')
        )

    def test_current_settings_saves_driving_defaults(self):
        response = self.client.put(
            self.current_settings_url,
            {'default_mpg': 31.5, 'default_gas_price_per_gallon': 5.29},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings.default_mpg, Decimal('31.5'))
        self.assertEqual(settings.default_gas_price_per_gallon, Decimal('5.29'))
