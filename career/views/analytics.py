from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..services.timeline_analytics import build_application_timeline_analytics


class ApplicationTimelineAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(build_application_timeline_analytics(request.user))
