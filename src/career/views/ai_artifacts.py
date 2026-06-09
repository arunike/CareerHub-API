from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.cache import cache

from ..models import AIArtifact, AIArtifactGenerationJob
from ..serializers import AIArtifactGenerationJobSerializer, AIArtifactSerializer
from ..cache import get_ai_artifacts_cache_key, invalidate_ai_artifacts_cache
from ..services.ai_artifact_jobs import start_ai_artifact_generation_thread


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

    def list(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = get_ai_artifacts_cache_key(user_id, "list", request.query_params)
        
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)
            
        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, timeout=300)
        return response

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
        invalidate_ai_artifacts_cache(request.user.id)
        return Response(
            {
                'message': f'Deleted {deleted} AI artifacts. Locked artifacts were preserved.',
                'deleted': deleted,
            },
            status=status.HTTP_200_OK,
        )


class AIArtifactGenerationJobViewSet(viewsets.ModelViewSet):
    serializer_class = AIArtifactGenerationJobSerializer
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return AIArtifactGenerationJob.objects.filter(user=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        job = serializer.save()
        start_ai_artifact_generation_thread(job.id)
