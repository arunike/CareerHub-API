from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from ..models import Experience
from ..serializers import ExperienceSerializer
from ..llm_matcher import generate_jd_match_evaluation

class ExperienceViewSet(viewsets.ModelViewSet):
    queryset = Experience.objects.all().order_by('-start_date', '-created_at')
    serializer_class = ExperienceSerializer

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
