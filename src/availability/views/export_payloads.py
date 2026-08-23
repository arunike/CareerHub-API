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


def _json_response(payload, filename):
    content = json.dumps(payload, indent=2, cls=DjangoJSONEncoder).encode('utf-8')
    response = HttpResponse(content, content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _zip_json_response(payload, filename):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('careerhub-account-export.json', json.dumps(payload, indent=2, cls=DjangoJSONEncoder))
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _model_payload(instance, exclude=()):
    data = model_to_dict(instance, exclude=list(exclude))
    data.pop('user', None)
    data.pop('id', None)
    return data
