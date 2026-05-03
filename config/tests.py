from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase


class SecurityDashboardTests(APITestCase):
    def test_security_dashboard_requires_authentication(self):
        response = self.client.get('/api/security/dashboard/')
        self.assertEqual(response.status_code, 401)

    def test_security_dashboard_returns_safe_summary(self):
        user = get_user_model().objects.create_user(
            username='security-dashboard@example.com',
            email='security-dashboard@example.com',
            password='pass12345',
        )
        self.client.force_authenticate(user=user)

        response = self.client.get('/api/security/dashboard/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('environment', response.data)
        self.assertIn('auth', response.data)
        self.assertIn('google', response.data)
        self.assertIn('waf', response.data)
        self.assertNotIn('SECRET_KEY', str(response.data))
        self.assertNotIn('GOOGLE_OAUTH_CLIENT_SECRET', str(response.data))
