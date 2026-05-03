from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import OfferDecisionSnapshot
from ..serializers import OfferDecisionSnapshotSerializer


class OfferDecisionSnapshotViewSet(viewsets.ModelViewSet):
    serializer_class = OfferDecisionSnapshotSerializer

    def get_queryset(self):
        queryset = (
            OfferDecisionSnapshot.objects.filter(user=self.request.user)
            .select_related('offer', 'offer__application', 'offer__application__company')
            .order_by('-captured_at')
        )
        offer_id = self.request.query_params.get('offer')
        if offer_id:
            queryset = queryset.filter(offer_id=offer_id)
        return queryset

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This decision snapshot is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        deleted, _ = self.get_queryset().filter(is_locked=False).delete()
        return Response(
            {
                'message': f'Deleted {deleted} decision snapshots. Locked snapshots were preserved.',
                'deleted': deleted,
            },
            status=status.HTTP_200_OK,
        )
