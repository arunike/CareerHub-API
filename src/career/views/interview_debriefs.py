from rest_framework import viewsets

from ..models import InterviewDebrief
from ..serializers import InterviewDebriefSerializer


class InterviewDebriefViewSet(viewsets.ModelViewSet):
    serializer_class = InterviewDebriefSerializer

    def get_queryset(self):
        queryset = InterviewDebrief.objects.filter(user=self.request.user).select_related(
            'application'
        )

        application = (self.request.query_params.get('application') or '').strip()
        if application:
            try:
                return queryset.filter(application_id=int(application))
            except ValueError:
                return queryset.none()

        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
