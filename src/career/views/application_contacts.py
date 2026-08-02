from rest_framework import viewsets
from rest_framework.response import Response

from ..models import ApplicationContact, Experience
from ..serializers import ApplicationContactSerializer


class ApplicationContactViewSet(viewsets.ModelViewSet):
    serializer_class = ApplicationContactSerializer

    def get_queryset(self):
        queryset = ApplicationContact.objects.filter(user=self.request.user).select_related(
            'application', 'experience'
        )

        application = (self.request.query_params.get('application') or '').strip()
        if application:
            try:
                return queryset.filter(application_id=int(application))
            except ValueError:
                return queryset.none()

        experience = (self.request.query_params.get('experience') or '').strip()
        if experience:
            try:
                return queryset.filter(experience_id=int(experience))
            except ValueError:
                return queryset.none()

        return queryset

    def _inherited_for_experience(self, experience_id, own):
        try:
            experience = Experience.objects.select_related('offer').get(
                id=int(experience_id), user=self.request.user
            )
        except (ValueError, Experience.DoesNotExist):
            return []

        application_id = getattr(experience.offer, 'application_id', None)
        if not application_id:
            return []

        own_ids = {contact.id for contact in own}
        inherited = []
        for contact in ApplicationContact.objects.filter(
            user=self.request.user, application_id=application_id
        ).select_related('application'):
            if contact.id in own_ids:
                continue
            contact._inherited = True
            inherited.append(contact)
        return inherited

    def list(self, request, *args, **kwargs):
        own = list(self.get_queryset())

        experience_id = (request.query_params.get('experience') or '').strip()
        inherited = self._inherited_for_experience(experience_id, own) if experience_id else []

        return Response(self.get_serializer(own + inherited, many=True).data)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
