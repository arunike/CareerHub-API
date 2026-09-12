import json
import re
from decimal import Decimal
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

from rest_framework.exceptions import ValidationError

from config.outbound import open_outbound_url

# The symbol is interpolated into a URL, so nothing but a ticker may get through.
SYMBOL_PATTERN = re.compile(r'^[A-Z0-9][A-Z0-9.\-]{0,11}$')

QUOTE_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d'

# Yahoo's chart endpoint is undocumented and refuses a request with no browser-shaped agent.
QUOTE_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; CareerHub)'}

QUOTE_TIMEOUT_SECONDS = 8


def normalize_symbol(value):
    symbol = str(value or '').strip().upper()
    if not SYMBOL_PATTERN.match(symbol):
        raise ValidationError({'symbol': 'That does not look like a ticker symbol.'})
    return symbol


def _price_from_payload(payload):
    chart = (payload or {}).get('chart') or {}
    if chart.get('error'):
        raise ValidationError({'symbol': 'No price was found for that symbol.'})
    results = chart.get('result') or []
    meta = (results[0] or {}).get('meta') if results else None
    if not meta:
        raise ValidationError({'symbol': 'No price was found for that symbol.'})
    price = meta.get('regularMarketPrice')
    if not isinstance(price, (int, float)) or price <= 0:
        raise ValidationError({'symbol': 'That symbol returned no usable price.'})
    traded_at = meta.get('regularMarketTime')
    as_of = (
        datetime.fromtimestamp(traded_at, tz=timezone.utc).date()
        if isinstance(traded_at, (int, float))
        else None
    )
    return {'price': float(price), 'as_of': as_of, 'currency': meta.get('currency') or 'USD'}


def fetch_quote(symbol):
    """The latest traded price for a ticker, or a validation error explaining why not."""
    ticker = normalize_symbol(symbol)
    try:
        with open_outbound_url(
            QUOTE_URL.format(symbol=ticker),
            timeout=QUOTE_TIMEOUT_SECONDS,
            headers=QUOTE_HEADERS,
            allow_http=False,
        ) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as error:
        if error.code == 404:
            raise ValidationError({'symbol': 'No price was found for that symbol.'})
        raise ValidationError({'symbol': 'The price service is unavailable right now.'})
    except (URLError, TimeoutError, ValueError):
        raise ValidationError({'symbol': 'The price service could not be reached.'})

    quote = _price_from_payload(payload)
    quote['symbol'] = ticker
    return quote


def record_price(*, user, symbol, price, as_of, source, note=''):
    """Write the latest price and append the day's history in one place, so both stay in step."""
    from career.models import StockPrice, StockPriceHistory

    ticker = normalize_symbol(symbol)
    latest, _ = StockPrice.objects.update_or_create(
        user=user,
        symbol=ticker,
        defaults={'price': price, 'as_of': as_of, 'source': source, 'note': note},
    )
    _append_history(
        user=user, symbol=ticker, price=price, as_of=as_of, source=source, note=note
    )
    return latest


def _append_history(*, user, symbol, price, as_of, source, note):
    """A log of changes, not of checks: an unchanged price adds nothing worth reading."""
    from career.models import StockPriceHistory

    rows = StockPriceHistory.objects.filter(user=user, symbol=symbol)
    same_day = rows.filter(as_of=as_of).first()
    if same_day:
        # That day is being corrected or refined intraday, so it is updated rather than duplicated.
        StockPriceHistory.objects.filter(pk=same_day.pk).update(
            price=price, source=source, note=note
        )
        return

    newest = rows.order_by('-as_of').first()
    if newest and Decimal(str(price)) == newest.price:
        return

    StockPriceHistory.objects.create(
        user=user, symbol=symbol, price=price, as_of=as_of, source=source, note=note
    )


def refresh_price(*, user, symbol):
    """Fetch the live price for a ticker and record it as the latest, with a history row."""
    from django.utils import timezone

    quote = fetch_quote(symbol)
    return record_price(
        user=user,
        symbol=quote['symbol'],
        price=quote['price'],
        as_of=quote['as_of'] or timezone.now().date(),
        source='API',
        note=f"Fetched at {quote['currency']}",
    )
