from rest_framework import viewsets

from ..models import Offer
from ..serializers import OfferSerializer


class OfferViewSet(viewsets.ModelViewSet):
    queryset = Offer.objects.select_related('application__company').all()
    serializer_class = OfferSerializer

    def get_queryset(self):
        return Offer.objects.select_related('application__company').filter(application__user=self.request.user)
