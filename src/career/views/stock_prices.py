from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import StockPrice, StockPriceHistory
from ..serializers import StockPriceHistorySerializer, StockPriceSerializer
from ..services.stock_quotes import normalize_symbol, refresh_price


class StockPriceViewSet(viewsets.ModelViewSet):
    """The latest price per ticker, kept once per user so several offers can share one."""

    serializer_class = StockPriceSerializer

    def get_queryset(self):
        return StockPrice.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['post'])
    def refresh(self, request):
        """Fetch live prices: one ticker when given, otherwise every ticker already tracked."""
        requested = request.data.get('symbol')
        symbols = (
            [normalize_symbol(requested)]
            if requested
            else list(self.get_queryset().values_list('symbol', flat=True))
        )
        if not symbols:
            return Response(
                {'detail': 'No ticker to refresh.'}, status=status.HTTP_400_BAD_REQUEST
            )

        updated, failed = [], []
        for symbol in symbols:
            try:
                updated.append(refresh_price(user=request.user, symbol=symbol))
            except Exception as error:  # noqa: BLE001 - one bad ticker must not fail the rest
                failed.append({'symbol': symbol, 'detail': str(getattr(error, 'detail', error))})

        # A single explicit ticker that failed is an error; a partial sweep still reports what worked.
        if requested and not updated:
            return Response(
                failed[0] if failed else {'detail': 'No price was found.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {'updated': StockPriceSerializer(updated, many=True).data, 'failed': failed}
        )

    @action(detail=False, methods=['get'])
    def history(self, request):
        """Every price recorded, newest first, optionally for one ticker."""
        rows = StockPriceHistory.objects.filter(user=request.user)
        symbol = request.query_params.get('symbol')
        if symbol:
            rows = rows.filter(symbol=normalize_symbol(symbol))
        return Response(StockPriceHistorySerializer(rows[:365], many=True).data)
