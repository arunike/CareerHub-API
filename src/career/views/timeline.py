from rest_framework import viewsets

from ..models import ApplicationTimelineEntry
from ..serializers import ApplicationTimelineEntrySerializer


class ApplicationTimelineEntryViewSet(viewsets.ModelViewSet):
    serializer_class = ApplicationTimelineEntrySerializer

    def get_queryset(self):
        queryset = (
            ApplicationTimelineEntry.objects.filter(user=self.request.user)
            .select_related('application', 'application__company')
            .prefetch_related('documents')
            .order_by('application_id', 'stage_order')
        )
        application_id = self.request.query_params.get('application')
        if application_id:
            queryset = queryset.filter(application_id=application_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
