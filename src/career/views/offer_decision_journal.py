from rest_framework import viewsets

from ..models import OfferDecisionJournal
from ..serializers import OfferDecisionJournalSerializer


class OfferDecisionJournalViewSet(viewsets.ModelViewSet):
    """Why each offer was taken or turned down, and the 30/90 day look back."""

    serializer_class = OfferDecisionJournalSerializer

    def get_queryset(self):
        return OfferDecisionJournal.objects.filter(
            offer__application__user=self.request.user
        ).select_related('offer', 'offer__application', 'offer__application__company')
