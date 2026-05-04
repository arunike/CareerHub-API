from rest_framework import viewsets

from ..models import Offer
from ..serializers import OfferSerializer
from ..services.offers import ensure_offers_for_offer_status_applications


class OfferViewSet(viewsets.ModelViewSet):
    queryset = Offer.objects.select_related('application__company').all()
    serializer_class = OfferSerializer

    def get_queryset(self):
        ensure_offers_for_offer_status_applications(self.request.user)
        return Offer.objects.select_related('application__company').filter(application__user=self.request.user)
