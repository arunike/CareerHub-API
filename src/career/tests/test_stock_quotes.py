import json
from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import StockPrice, StockPriceHistory
from ..services.stock_quotes import normalize_symbol

REFRESH_URL = '/api/career/stock-prices/refresh/'
HISTORY_URL = '/api/career/stock-prices/history/'


class SymbolValidationTests(APITestCase):
    """The ticker is interpolated into a URL, so anything but a ticker has to be refused."""

    def test_accepts_a_plain_ticker_and_uppercases_it(self):
        self.assertEqual(normalize_symbol(' goog '), 'GOOG')
        self.assertEqual(normalize_symbol('brk.b'), 'BRK.B')
        self.assertEqual(normalize_symbol('rds-a'), 'RDS-A')

    def test_refuses_anything_that_could_steer_the_request(self):
        from rest_framework.exceptions import ValidationError

        for bad in ['', '../etc', 'GOOG/../x', 'GOOG?x=1', 'a b', 'GOOG#f', 'A' * 13, 'http://x']:
            with self.assertRaises(ValidationError, msg=bad):
                normalize_symbol(bad)


def _chart_payload(price=335.45, traded_at=1789156801):
    return json.dumps(
        {
            'chart': {
                'result': [
                    {
                        'meta': {
                            'regularMarketPrice': price,
                            'regularMarketTime': traded_at,
                            'currency': 'USD',
                        }
                    }
                ],
                'error': None,
            }
        }
    ).encode('utf-8')


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class StockPriceRefreshTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="quotes@example.com",
            email="quotes@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_fetches_a_price_and_records_it_as_the_latest(self, mock_open):
        mock_open.return_value = _FakeResponse(_chart_payload())
        response = self.client.post(REFRESH_URL, {'symbol': 'goog'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        latest = StockPrice.objects.get(user=self.user, symbol='GOOG')
        self.assertEqual(float(latest.price), 335.45)
        self.assertEqual(latest.source, 'API')

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_the_request_goes_through_the_outbound_guard_over_https(self, mock_open):
        mock_open.return_value = _FakeResponse(_chart_payload())
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')

        url = mock_open.call_args.args[0]
        self.assertTrue(url.startswith('https://'))
        self.assertIn('GOOG', url)
        self.assertFalse(mock_open.call_args.kwargs['allow_http'])

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_appends_one_history_row_per_trading_day(self, mock_open):
        mock_open.return_value = _FakeResponse(_chart_payload())
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')

        rows = StockPriceHistory.objects.filter(user=self.user, symbol='GOOG')
        self.assertEqual(rows.count(), 1)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_a_new_trading_day_adds_a_row_rather_than_replacing(self, mock_open):
        mock_open.return_value = _FakeResponse(_chart_payload(price=300))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')
        mock_open.return_value = _FakeResponse(_chart_payload(price=340, traded_at=1789243201))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')

        self.assertEqual(StockPriceHistory.objects.filter(user=self.user).count(), 2)
        self.assertEqual(float(StockPrice.objects.get(user=self.user).price), 340)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_reports_a_symbol_with_no_price(self, mock_open):
        mock_open.return_value = _FakeResponse(
            json.dumps({'chart': {'result': None, 'error': {'code': 'Not Found'}}}).encode()
        )
        response = self.client.post(REFRESH_URL, {'symbol': 'NOPE'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(StockPrice.objects.filter(user=self.user).exists())

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_a_network_failure_does_not_wipe_the_stored_price(self, mock_open):
        StockPrice.objects.create(
            user=self.user, symbol='GOOG', price=200, as_of=date(2026, 7, 1), source='MANUAL'
        )
        mock_open.side_effect = TimeoutError()
        response = self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(float(StockPrice.objects.get(user=self.user).price), 200)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_refreshes_every_tracked_ticker_when_none_is_named(self, mock_open):
        for symbol in ('GOOG', 'NFLX'):
            StockPrice.objects.create(
                user=self.user, symbol=symbol, price=1, as_of=date(2026, 7, 1), source='MANUAL'
            )
        mock_open.return_value = _FakeResponse(_chart_payload())
        response = self.client.post(REFRESH_URL, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['updated']), 2)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_one_bad_ticker_does_not_stop_the_sweep(self, mock_open):
        for symbol in ('GOOG', 'NFLX'):
            StockPrice.objects.create(
                user=self.user, symbol=symbol, price=1, as_of=date(2026, 7, 1), source='MANUAL'
            )
        mock_open.side_effect = [
            _FakeResponse(_chart_payload()),
            TimeoutError(),
        ]
        response = self.client.post(REFRESH_URL, {}, format='json')

        self.assertEqual(len(response.data['updated']), 1)
        self.assertEqual(len(response.data['failed']), 1)

    def test_refusing_to_refresh_with_nothing_tracked(self):
        response = self.client.post(REFRESH_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class HistoryRecordsChangesNotChecksTests(APITestCase):
    """Refreshing on every open would otherwise fill the log with identical rows."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="history-changes@example.com",
            email="history-changes@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_an_unchanged_price_on_a_new_day_adds_no_row(self, mock_open):
        mock_open.return_value = _FakeResponse(_chart_payload(price=335.45))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')
        # Same price, next trading day.
        mock_open.return_value = _FakeResponse(_chart_payload(price=335.45, traded_at=1789243201))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')

        self.assertEqual(StockPriceHistory.objects.filter(user=self.user).count(), 1)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_the_latest_pointer_still_moves_to_the_newer_date(self, mock_open):
        mock_open.return_value = _FakeResponse(_chart_payload(price=335.45))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')
        mock_open.return_value = _FakeResponse(_chart_payload(price=335.45, traded_at=1789243201))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')

        expected = datetime.fromtimestamp(1789243201, tz=dt_timezone.utc).date()
        latest = StockPrice.objects.get(user=self.user, symbol='GOOG')
        self.assertEqual(latest.as_of, expected)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_a_changed_price_adds_a_row(self, mock_open):
        mock_open.return_value = _FakeResponse(_chart_payload(price=335.45))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')
        mock_open.return_value = _FakeResponse(_chart_payload(price=340, traded_at=1789243201))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')

        self.assertEqual(StockPriceHistory.objects.filter(user=self.user).count(), 2)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_a_price_that_returns_to_an_earlier_value_is_still_recorded(self, mock_open):
        for price, traded_at in ((300, 1789156801), (340, 1789243201), (300, 1789329601)):
            mock_open.return_value = _FakeResponse(_chart_payload(price=price, traded_at=traded_at))
            self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')

        # Compared against the row before it, not against every row ever recorded.
        self.assertEqual(StockPriceHistory.objects.filter(user=self.user).count(), 3)

    @patch('career.services.stock_quotes.open_outbound_url')
    def test_an_intraday_move_refines_the_same_day_rather_than_adding(self, mock_open):
        mock_open.return_value = _FakeResponse(_chart_payload(price=335.45))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')
        mock_open.return_value = _FakeResponse(_chart_payload(price=338.10))
        self.client.post(REFRESH_URL, {'symbol': 'GOOG'}, format='json')

        rows = StockPriceHistory.objects.filter(user=self.user, symbol='GOOG')
        self.assertEqual(rows.count(), 1)
        self.assertEqual(float(rows.first().price), 338.10)


class StockPriceHistoryTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="history@example.com",
            email="history@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_a_hand_entered_price_is_recorded_in_history_too(self):
        response = self.client.post(
            '/api/career/stock-prices/',
            {'symbol': 'GOOG', 'price': '137.50', 'as_of': '2026-07-01'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(StockPriceHistory.objects.filter(user=self.user).count(), 1)

    def test_lists_history_newest_first_and_can_narrow_to_one_ticker(self):
        for symbol, as_of, price in (
            ('GOOG', date(2026, 7, 1), 100),
            ('GOOG', date(2026, 8, 1), 120),
            ('NFLX', date(2026, 8, 1), 500),
        ):
            StockPriceHistory.objects.create(
                user=self.user, symbol=symbol, price=price, as_of=as_of, source='API'
            )

        listed = self.client.get(HISTORY_URL)
        self.assertEqual(len(listed.data), 3)
        self.assertEqual(listed.data[0]['as_of'], '2026-08-01')

        narrowed = self.client.get(HISTORY_URL, {'symbol': 'goog'})
        self.assertEqual([row['symbol'] for row in narrowed.data], ['GOOG', 'GOOG'])

    def test_does_not_show_another_users_history(self):
        stranger = get_user_model().objects.create_user(
            username="stranger-history@example.com",
            email="stranger-history@example.com",
            password="StrongPassw0rd!",
        )
        StockPriceHistory.objects.create(
            user=stranger, symbol='NFLX', price=500, as_of=date(2026, 8, 1), source='API'
        )
        self.assertEqual(self.client.get(HISTORY_URL).data, [])

    def test_history_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(HISTORY_URL).status_code, status.HTTP_401_UNAUTHORIZED)
