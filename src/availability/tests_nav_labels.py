"""Custom sidebar names."""

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase


class NavItemLabelTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='nav-labels@example.com',
            email='nav-labels@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_authenticate(self.user)
        self.url = '/api/user-settings/current/'

    def patch(self, labels):
        return self.client.put(self.url, {'nav_item_labels': labels}, format='json')

    def test_defaults_to_no_custom_names(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['nav_item_labels'], {})

    def test_saves_a_custom_name(self):
        response = self.patch({'/tasks': 'To Do'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['nav_item_labels'], {'/tasks': 'To Do'})

    def test_trims_a_custom_name(self):
        self.assertEqual(self.patch({'/offers': '  Comp  '}).data['nav_item_labels'], {'/offers': 'Comp'})

    def test_drops_a_blank_name_so_the_default_returns(self):
        self.patch({'/tasks': 'To Do'})
        self.assertEqual(self.patch({'/tasks': '   '}).data['nav_item_labels'], {})

    def test_renames_a_group_and_a_nested_entry(self):
        labels = {'grp-1': 'Calendar', 'intelligence': 'AI', '/jd-reports': 'Reports'}
        self.assertEqual(self.patch(labels).data['nav_item_labels'], labels)

    def test_rejects_an_unknown_key(self):
        response = self.patch({'/not-a-route': 'Nope'})
        self.assertEqual(response.status_code, 400)

    def test_rejects_the_toolbar_placeholder(self):
        self.assertEqual(self.patch({'__smart__': 'Smart'}).status_code, 400)

    def test_rejects_a_name_that_is_not_text(self):
        self.assertEqual(self.patch({'/tasks': 5}).status_code, 400)

    def test_rejects_a_list_instead_of_an_object(self):
        self.assertEqual(self.patch(['/tasks']).status_code, 400)

    def test_rejects_an_overlong_name(self):
        self.assertEqual(self.patch({'/tasks': 'x' * 41}).status_code, 400)
        self.assertEqual(self.patch({'/tasks': 'x' * 40}).status_code, 200)
