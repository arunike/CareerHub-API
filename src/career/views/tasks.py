from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.cache import cache

from ..models import Task
from ..serializers import TaskSerializer
from ..cache import get_tasks_cache_key, invalidate_tasks_cache


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all().order_by('status', 'position', '-updated_at')
    serializer_class = TaskSerializer

    def get_queryset(self):
        return Task.objects.filter(user=self.request.user).order_by('status', 'position', '-updated_at')

    def list(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = get_tasks_cache_key(user_id, "list", request.query_params)
        
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)
            
        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, timeout=300)
        return response

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        updates = request.data.get('updates', [])
        if not isinstance(updates, list):
            return Response({'error': 'updates must be a list'}, status=status.HTTP_400_BAD_REQUEST)

        for item in updates:
            task_id = item.get('id')
            if task_id is None:
                continue
            Task.objects.filter(id=task_id, user=request.user).update(
                status=item.get('status', 'TODO'),
                position=item.get('position', 0),
            )
            
        invalidate_tasks_cache(request.user.id)
        return Response({'message': 'Tasks reordered successfully'}, status=status.HTTP_200_OK)
