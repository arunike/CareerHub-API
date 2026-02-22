from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import Task
from ..serializers import TaskSerializer


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all().order_by('status', 'position', '-updated_at')
    serializer_class = TaskSerializer

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        updates = request.data.get('updates', [])
        if not isinstance(updates, list):
            return Response({'error': 'updates must be a list'}, status=status.HTTP_400_BAD_REQUEST)

        for item in updates:
            task_id = item.get('id')
            if task_id is None:
                continue
            Task.objects.filter(id=task_id).update(
                status=item.get('status', 'TODO'),
                position=item.get('position', 0),
            )
        return Response({'message': 'Tasks reordered successfully'}, status=status.HTTP_200_OK)
