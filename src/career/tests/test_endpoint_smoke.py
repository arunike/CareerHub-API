from django.contrib.auth import get_user_model
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APITestCase

from ..models import GoogleSheetSyncConfig


def _list_paths():
    """Every GET-able collection route with no URL arguments."""
    paths = set()

    def walk(patterns, prefix=''):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                route = prefix + str(entry.pattern)
                if '<' in route or '(?P<' in route:
                    continue
                callback = entry.callback
                actions = getattr(callback, 'actions', None)
                if not actions or 'get' not in actions:
                    continue
                paths.add('/' + route.lstrip('/'))

    walk(get_resolver().url_patterns)
    return sorted(paths)


class ListEndpointSmokeTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='smoke@example.com',
            email='smoke@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_authenticate(self.user)

    def test_the_router_exposes_endpoints_to_check(self):
        # Guards the walker itself: a silent zero would make the sweep below vacuous.
        self.assertGreater(len(_list_paths()), 15)

    def test_no_list_endpoint_returns_a_server_error(self):
        failures = []
        for path in _list_paths():
            try:
                response = self.client.get(path)
            except Exception as exc:  # noqa: BLE001 - the point is to report, not to raise
                failures.append(f'{path} raised {type(exc).__name__}: {exc}')
                continue
            if response.status_code >= 500:
                failures.append(f'{path} returned {response.status_code}')
        self.assertEqual(failures, [], 'Endpoints failed:\n' + '\n'.join(failures))


class GoogleSheetSyncListTests(APITestCase):
    """A row has to exist: the broken import sat in a per-row SerializerMethodField, so an
    empty list serialised fine and the endpoint only failed once there was data."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='sheet-list@example.com',
            email='sheet-list@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_authenticate(self.user)
        GoogleSheetSyncConfig.objects.create(
            user=self.user,
            name='Applications',
            sheet_url='https://docs.google.com/spreadsheets/d/abc123/edit#gid=0',
            spreadsheet_id='abc123',
        )

    def test_lists_a_saved_sync_without_a_server_error(self):
        response = self.client.get('/api/career/google-sheet-syncs/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_reports_the_address_a_sheet_must_be_shared_with(self):
        response = self.client.get('/api/career/google-sheet-syncs/')
        # The field that carried the broken import; present even when unconfigured.
        self.assertIn('share_with_email', response.data[0])
