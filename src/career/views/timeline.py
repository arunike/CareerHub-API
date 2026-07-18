from django.utils import timezone
from rest_framework import viewsets

from ..models import ApplicationTimelineEntry
from ..serializers import ApplicationTimelineEntrySerializer


class ApplicationTimelineEntryViewSet(viewsets.ModelViewSet):
    serializer_class = ApplicationTimelineEntrySerializer

    def get_queryset(self):
        queryset = (
            ApplicationTimelineEntry.objects.filter(
                user=self.request.user,
                deleted_by_user_at__isnull=True,
                hidden_by_sync_at__isnull=True,
            )
            .select_related('application', 'application__company')
            .prefetch_related('documents')
            .order_by('application_id', 'stage_order', 'event_date', 'created_at')
        )
        application_id = self.request.query_params.get('application')
        if application_id:
            queryset = queryset.filter(application_id=application_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_destroy(self, instance):
        instance.deleted_by_user_at = timezone.now()
        instance.save(update_fields=['deleted_by_user_at', 'updated_at'])
