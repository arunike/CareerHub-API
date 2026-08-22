from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from availability.models import UserSettings
from career.models import Application, Company
from career.tasks import auto_ghost_stale_applications


class AutoGhostStaleApplicationsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='ghosting-user@example.com',
            email='ghosting-user@example.com',
            password='StrongPassw0rd!',
        )
        self.company = Company.objects.create(user=self.user, name='Google')
        UserSettings.objects.create(user=self.user, ghosting_threshold_days=30)

    def create_application(self, *, status='APPLIED', days_old=30, role_title='Software Engineer'):
        return Application.objects.create(
            user=self.user,
            company=self.company,
            role_title=role_title,
            status=status,
            date_applied=timezone.localdate() - timedelta(days=days_old),
        )

    @patch('career.cache.invalidate_applications_cache')
    def test_ghosts_only_applied_applications_that_reach_the_date_threshold(
        self,
        invalidate_cache,
    ):
        stale_applied = self.create_application(role_title='Stale applied')
        fresh_applied = self.create_application(days_old=29, role_title='Fresh applied')
        active_interview = self.create_application(
            status='ROUND_1',
            days_old=60,
            role_title='Active interview',
        )
        terminal_offer = self.create_application(
            status='OFFER',
            days_old=60,
            role_title='Offer',
        )
        missing_date = self.create_application(role_title='Missing date')
        missing_date.date_applied = None
        missing_date.save(update_fields=['date_applied'])

        result = auto_ghost_stale_applications()

        stale_applied.refresh_from_db()
        fresh_applied.refresh_from_db()
        active_interview.refresh_from_db()
        terminal_offer.refresh_from_db()
        missing_date.refresh_from_db()

        self.assertEqual(stale_applied.status, 'GHOSTED')
        self.assertEqual(fresh_applied.status, 'APPLIED')
        self.assertEqual(active_interview.status, 'ROUND_1')
        self.assertEqual(terminal_offer.status, 'OFFER')
        self.assertEqual(missing_date.status, 'APPLIED')
        self.assertEqual(result, 'Ghosted 1 stale application(s).')
        invalidate_cache.assert_called_once_with(self.user.id)

    def test_uses_each_users_configured_threshold(self):
        other_user = get_user_model().objects.create_user(
            username='custom-ghosting-user@example.com',
            email='custom-ghosting-user@example.com',
            password='StrongPassw0rd!',
        )
        other_company = Company.objects.create(user=other_user, name='Custom Threshold Co')
        UserSettings.objects.create(user=other_user, ghosting_threshold_days=10)
        custom_stale = Application.objects.create(
            user=other_user,
            company=other_company,
            role_title='Custom stale',
            status='APPLIED',
            date_applied=timezone.localdate() - timedelta(days=10),
        )
        default_fresh = self.create_application(days_old=10, role_title='Default fresh')

        result = auto_ghost_stale_applications()

        custom_stale.refresh_from_db()
        default_fresh.refresh_from_db()
        self.assertEqual(custom_stale.status, 'GHOSTED')
        self.assertEqual(default_fresh.status, 'APPLIED')
        self.assertEqual(result, 'Ghosted 1 stale application(s).')
