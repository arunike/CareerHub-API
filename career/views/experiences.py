from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView
from rest_framework.response import Response
from ..models import Experience
from ..serializers import ExperienceSerializer
from ..llm_matcher import generate_jd_match_evaluation

class ExperienceViewSet(viewsets.ModelViewSet):
    queryset = Experience.objects.all().order_by('-start_date', '-created_at')
    serializer_class = ExperienceSerializer

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        locked = instance.is_locked or False
        if locked and not (len(request.data) == 1 and 'is_locked' in request.data):
            return Response({'error': 'This experience is locked and cannot be edited.'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked or False:
            return Response({'error': 'This experience is locked and cannot be deleted.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['delete'], url_path='delete_all')
    def delete_all(self, request):
        Experience.objects.filter(is_locked__in=[False, None]).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='upload-logo', parser_classes=[MultiPartParser])
    def upload_logo(self, request, pk=None):
        instance = self.get_object()
        if 'logo' not in request.FILES:
            return Response({'error': 'No logo file provided.'}, status=status.HTTP_400_BAD_REQUEST)
        # Delete old file from storage before replacing
        if instance.logo:
            instance.logo.delete(save=False)
        instance.logo = request.FILES['logo']
        instance.save(update_fields=['logo'])
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['delete'], url_path='remove-logo')
    def remove_logo(self, request, pk=None):
        instance = self.get_object()
        if instance.logo:
            instance.logo.delete(save=False)
            instance.logo = None
            instance.save(update_fields=['logo'])
        return Response(self.get_serializer(instance).data)

class MatchJDView(APIView):
    def post(self, request, *args, **kwargs):
        text = request.data.get('text', '')
        if not text:
            return Response({'error': 'No job description provided.'}, status=400)
            
        try:
            evaluation = generate_jd_match_evaluation(text)
            return Response(evaluation)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
