from django.core.cache import cache
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..cache import get_applications_cache_key
from ..services.application_stats import build_application_stats
from ..services.timeline_analytics import build_application_timeline_analytics


def _requested_year(request):
    raw_year = request.query_params.get('year')
    if raw_year and raw_year != 'all':
        try:
            return int(raw_year)
        except (TypeError, ValueError):
            return None
    return None


class ApplicationStatsView(APIView):
    """Dashboard counts without shipping the applications themselves.

    The Analytics page needed totals, location and age groupings, and one date per
    application. Fetching the list for that meant ~1 MB of job descriptions and notes per
    page load; this returns the same figures in a few KB.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cache_key = get_applications_cache_key(request.user.id, "stats", request.query_params)
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)

        data = build_application_stats(request.user, year=_requested_year(request))
        cache.set(cache_key, data, timeout=300)
        return Response(data)


class ApplicationTimelineAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = request.user.id
        cache_key = get_applications_cache_key(user_id, "analytics", request.query_params)
        
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)
            
        data = build_application_timeline_analytics(request.user, year=_requested_year(request))
        cache.set(cache_key, data, timeout=300)
        return Response(data)
