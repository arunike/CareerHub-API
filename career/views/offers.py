from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import Offer
from ..serializers import OfferSerializer


class OfferViewSet(viewsets.ModelViewSet):
    queryset = Offer.objects.select_related('application__company').all()
    serializer_class = OfferSerializer

    @action(detail=True, methods=['post'], url_path='negotiation-advice')
    def negotiation_advice(self, request, pk=None):
        offer = self.get_object()
        current_offer = Offer.objects.filter(is_current=True).exclude(pk=offer.pk).first()
        try:
            from ..llm_matcher import generate_negotiation_advice
            advice = generate_negotiation_advice(offer, current_offer)
            return Response(advice)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
