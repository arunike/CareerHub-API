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


class EventCategoryViewSet(viewsets.ModelViewSet):
    queryset = EventCategory.objects.all()
    serializer_class = EventCategorySerializer

    def get_queryset(self):
        return EventCategory.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
