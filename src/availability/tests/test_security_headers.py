from django.test import TestCase


class SecurityHeaderTests(TestCase):
    """Headers Django has no setting for, so nothing else asserts they are present."""

    def test_api_responses_carry_a_locked_down_csp(self):
        response = self.client.get('/api/events/')
        self.assertEqual(
            response['Content-Security-Policy'],
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )

    def test_unauthenticated_responses_carry_them_too(self):
        response = self.client.get('/api/events/')
        self.assertEqual(response.status_code, 401)
        self.assertIn('Permissions-Policy', response)
        self.assertEqual(response['Cross-Origin-Opener-Policy'], 'same-origin')
        self.assertEqual(response['Cross-Origin-Resource-Policy'], 'same-site')

    def test_the_clickjacking_and_sniffing_headers_are_still_set(self):
        response = self.client.get('/api/events/')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
