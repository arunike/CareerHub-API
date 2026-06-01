from django.core.cache import cache
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..cache import get_applications_cache_key
from ..services.timeline_analytics import build_application_timeline_analytics


class ApplicationTimelineAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = request.user.id
        cache_key = get_applications_cache_key(user_id, "analytics", request.query_params)
        
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)
            
        data = build_application_timeline_analytics(request.user)
        cache.set(cache_key, data, timeout=300)
        return Response(data)
