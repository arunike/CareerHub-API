import logging
import io
import json
import zipfile
from datetime import datetime

import pandas as pd
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.forms.models import model_to_dict
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from career.models import (
    AIArtifact,
    Application,
    ApplicationTimelineEntry,
    Company,
    Document,
    Experience,
    Offer,
    OfferDecisionSnapshot,
    Task,
)
from career.serializers import (
    AIArtifactSerializer,
    ApplicationExportSerializer,
    DocumentExportSerializer,
    ExperienceExportSerializer,
    OfferDecisionSnapshotSerializer,
    OfferExportSerializer,
    TaskSerializer,
)

from ..ai_provider import AIProviderConfigurationError, AIProviderRequestError, relay_ai_provider_chat_completion
from ..models import (
    AvailabilityOverride,
    AvailabilitySetting,
    ConflictAlert,
    CustomHoliday,
    Event,
    EventCategory,
    PublicBooking,
    ShareLink,
    UserSettings,
)
from ..timezones import DEFAULT_TIMEZONE
from ..serializers import (
    AIProviderChatCompletionRequestSerializer,
    AvailabilityOverrideSerializer,
    AvailabilitySettingSerializer,
    ConflictAlertSerializer,
    CustomHolidaySerializer,
    EventCategorySerializer,
    EventSerializer,
    PublicBookingSerializer,
    ShareLinkSerializer,
    UserSettingsSerializer,
)
from ..throttling import AIProviderRelayThrottle


class ConflictAlertViewSet(viewsets.ModelViewSet):
    queryset = ConflictAlert.objects.all()
    serializer_class = ConflictAlertSerializer

    def get_queryset(self):
        return ConflictAlert.objects.filter(event1__user=self.request.user)

    @action(detail=False, methods=['get'])
    def unresolved(self, request):
        conflicts = self.get_queryset().filter(resolved=False)
        serializer = self.get_serializer(conflicts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        conflict = self.get_object()
        conflict.resolved = True
        conflict.save()
        return Response({'message': 'Conflict resolved'})
