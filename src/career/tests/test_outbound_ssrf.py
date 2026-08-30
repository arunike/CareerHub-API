from unittest.mock import patch

from django.test import SimpleTestCase

from config.outbound import OutboundURLError, validate_outbound_url


def _resolves_to(address):
    """Pin DNS so the test does not depend on the network."""
    return patch(
        'config.outbound.socket.getaddrinfo',
        return_value=[(2, 1, 6, '', (address, 0))],
    )


class ValidateOutboundURLTests(SimpleTestCase):
    def test_allows_a_public_address(self):
        with _resolves_to('93.184.216.34'):
            self.assertEqual(
                validate_outbound_url('https://example.com/logo.png'),
                'https://example.com/logo.png',
            )

    def test_blocks_the_cloud_metadata_endpoint(self):
        with _resolves_to('169.254.169.254'):
            with self.assertRaises(OutboundURLError):
                validate_outbound_url('http://169.254.169.254/latest/meta-data/')

    def test_blocks_loopback(self):
        for address in ('127.0.0.1', '::1'):
            with self.subTest(address=address), _resolves_to(address):
                with self.assertRaises(OutboundURLError):
                    validate_outbound_url(f'http://{address}/')

    def test_blocks_private_ranges(self):
        for address in ('10.0.0.5', '172.16.0.1', '192.168.1.1'):
            with self.subTest(address=address), _resolves_to(address):
                with self.assertRaises(OutboundURLError):
                    validate_outbound_url(f'http://{address}/')

    def test_blocks_a_public_name_that_resolves_somewhere_private(self):
        # The whole point: the hostname says nothing, the resolved address decides.
        with _resolves_to('127.0.0.1'):
            with self.assertRaises(OutboundURLError):
                validate_outbound_url('https://totally-normal.example.com/x')

    def test_blocks_a_host_with_one_private_answer_among_public_ones(self):
        infos = [(2, 1, 6, '', ('93.184.216.34', 0)), (2, 1, 6, '', ('10.1.2.3', 0))]
        with patch('config.outbound.socket.getaddrinfo', return_value=infos):
            with self.assertRaises(OutboundURLError):
                validate_outbound_url('https://split-horizon.example.com/x')

    def test_blocks_non_http_schemes(self):
        for url in ('file:///etc/passwd', 'gopher://example.com/', 'ftp://example.com/x'):
            with self.subTest(url=url):
                with self.assertRaises(OutboundURLError):
                    validate_outbound_url(url)

    def test_blocks_an_unusual_port(self):
        with _resolves_to('93.184.216.34'):
            with self.assertRaises(OutboundURLError):
                validate_outbound_url('http://example.com:6379/')

    def test_blocks_a_url_with_no_host(self):
        with self.assertRaises(OutboundURLError):
            validate_outbound_url('http:///nowhere')

    def test_blocks_an_empty_value(self):
        for value in ('', None, 123):
            with self.subTest(value=value):
                with self.assertRaises(OutboundURLError):
                    validate_outbound_url(value)

    def test_can_require_https(self):
        with _resolves_to('93.184.216.34'):
            with self.assertRaises(OutboundURLError):
                validate_outbound_url('http://example.com/x', allow_http=False)

    def test_reports_a_name_that_does_not_resolve(self):
        import socket as socket_module

        with patch('config.outbound.socket.getaddrinfo', side_effect=socket_module.gaierror()):
            with self.assertRaises(OutboundURLError):
                validate_outbound_url('https://no-such-host.example/')


class RedirectRevalidationTests(SimpleTestCase):
    def test_a_redirect_to_a_private_address_is_refused(self):
        from config.outbound import _ValidatingRedirectHandler

        handler = _ValidatingRedirectHandler()
        with _resolves_to('169.254.169.254'):
            with self.assertRaises(OutboundURLError):
                handler.redirect_request(
                    None, None, 302, 'Found', {}, 'http://169.254.169.254/latest/meta-data/'
                )
