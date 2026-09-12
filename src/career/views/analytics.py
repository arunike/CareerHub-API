from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..services.application_stats import build_application_stats
from ..services.decision_outcomes import build_decision_outcome_insights
from ..services.resume_analytics import build_resume_version_analytics
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
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(build_application_stats(request.user, year=_requested_year(request)))


class ApplicationTimelineAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            build_application_timeline_analytics(request.user, year=_requested_year(request))
        )


class ResumeVersionAnalyticsView(APIView):
    """How each submitted resume version performed, from the versions already on record."""

    permission_classes = [IsAuthenticated]

    # Uncached on purpose: LocMemCache is per instance, so attaching a resume would go stale.
    def get(self, request):
        data = build_resume_version_analytics(request.user, year=_requested_year(request))
        return Response(data)


class DecisionOutcomeInsightsView(APIView):
    """What the 30/90 day look-backs say across every decision, not one at a time."""

    permission_classes = [IsAuthenticated]

    # Uncached for the same reason as the resume view: a saved look-back must show up at once.
    def get(self, request):
        return Response(build_decision_outcome_insights(request.user))
