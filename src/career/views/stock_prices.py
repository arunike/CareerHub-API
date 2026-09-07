from rest_framework import viewsets

from ..models import StockPrice
from ..serializers import StockPriceSerializer


class StockPriceViewSet(viewsets.ModelViewSet):
    """The latest price per ticker, kept once per user so several offers can share one."""

    serializer_class = StockPriceSerializer

    def get_queryset(self):
        return StockPrice.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)
