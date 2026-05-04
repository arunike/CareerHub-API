from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import AIArtifact
from ..serializers import AIArtifactSerializer


class AIArtifactViewSet(viewsets.ModelViewSet):
    serializer_class = AIArtifactSerializer

    def get_queryset(self):
        queryset = AIArtifact.objects.filter(user=self.request.user)
        artifact_type = self.request.query_params.get('artifact_type')
        search = (self.request.query_params.get('search') or '').strip()
        if artifact_type:
            queryset = queryset.filter(artifact_type=artifact_type)
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(summary__icontains=search)
                | Q(client_id__icontains=search)
            )
        return queryset.order_by('-saved_at', '-created_at')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This AI artifact is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        deleted, _ = self.get_queryset().filter(is_locked=False).delete()
        return Response(
            {
                'message': f'Deleted {deleted} AI artifacts. Locked artifacts were preserved.',
                'deleted': deleted,
            },
            status=status.HTTP_200_OK,
        )
