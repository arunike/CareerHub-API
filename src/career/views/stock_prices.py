from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import StockPrice, StockPriceHistory
from ..serializers import StockPriceHistorySerializer, StockPriceSerializer
from ..services.stock_quotes import backfill_history, normalize_symbol, refresh_price

# A daily series over four years of vesting, which a 365-row cap would silently cut short.
HISTORY_PAGE_SIZE = 1500


class StockPriceViewSet(viewsets.ModelViewSet):
    """The latest price per ticker, kept once per user so several offers can share one."""

    serializer_class = StockPriceSerializer

    def get_queryset(self):
        return StockPrice.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)

    def _requested_symbols(self, request):
        requested = request.data.get('symbol')
        symbols = (
            [normalize_symbol(requested)]
            if requested
            else list(self.get_queryset().values_list('symbol', flat=True))
        )
        return requested, symbols

    def _sweep(self, symbols, run):
        done, failed = [], []
        for symbol in symbols:
            try:
                done.append(run(symbol))
            except Exception as error:  # noqa: BLE001 - one bad ticker must not fail the rest
                failed.append({'symbol': symbol, 'detail': str(getattr(error, 'detail', error))})
        return done, failed

    @action(detail=False, methods=['post'])
    def refresh(self, request):
        """Fetch live prices: one ticker when given, otherwise every ticker already tracked."""
        requested, symbols = self._requested_symbols(request)
        if not symbols:
            return Response(
                {'detail': 'No ticker to refresh.'}, status=status.HTTP_400_BAD_REQUEST
            )

        updated, failed = self._sweep(
            symbols, lambda symbol: refresh_price(user=request.user, symbol=symbol)
        )

        # A single explicit ticker that failed is an error; a partial sweep still reports what worked.
        if requested and not updated:
            return Response(
                failed[0] if failed else {'detail': 'No price was found.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {'updated': StockPriceSerializer(updated, many=True).data, 'failed': failed}
        )

    @action(detail=False, methods=['post'])
    def backfill(self, request):
        """Fill the daily log from the provider's own series, not just what was collected here."""
        requested, symbols = self._requested_symbols(request)
        if not symbols:
            return Response(
                {'detail': 'No ticker to backfill.'}, status=status.HTTP_400_BAD_REQUEST
            )

        period = request.data.get('period') or '2y'
        filled, failed = self._sweep(
            symbols,
            lambda symbol: backfill_history(user=request.user, symbol=symbol, period=period),
        )

        if requested and not filled:
            return Response(
                failed[0] if failed else {'detail': 'No price history was found.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'filled': filled, 'failed': failed})

    @action(detail=False, methods=['get'])
    def history(self, request):
        """Every price recorded, newest first, optionally for one ticker and from one date on."""
        rows = StockPriceHistory.objects.filter(user=request.user)
        symbol = request.query_params.get('symbol')
        if symbol:
            rows = rows.filter(symbol=normalize_symbol(symbol))
        since = parse_date(request.query_params.get('since') or '')
        if since:
            rows = rows.filter(as_of__gte=since)
        return Response(StockPriceHistorySerializer(rows[:HISTORY_PAGE_SIZE], many=True).data)
