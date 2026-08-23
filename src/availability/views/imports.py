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

logger = logging.getLogger(__name__)


class ImportViewSet(viewsets.ViewSet):
    def create(self, request):
        from ..utils import parse_import_file

        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=400)

        filename = file_obj.name.lower()
        file_type = 'json' if filename.endswith('.json') else 'ics' if filename.endswith('.ics') else None
        if not file_type:
            return Response({'error': 'Unsupported file type. Use .json or .ics'}, status=400)

        items = parse_import_file(file_obj, file_type)
        created_count = 0
        skipped_count = 0
        for item in items:
            try:
                if item['classification'] == 'holiday':
                    CustomHoliday.objects.create(
                        user=request.user,
                        date=item['date'],
                        description=item['summary'],
                        is_recurring=True,
                    )
                else:
                    Event.objects.create(
                        user=request.user,
                        name=item['summary'],
                        date=item['date'],
                        start_time=item['start_time'],
                        end_time=item['end_time'],
                        timezone=DEFAULT_TIMEZONE,
                    )
                created_count += 1
            except Exception:
                skipped_count += 1

        if skipped_count:
            logger.warning(
                'Availability import skipped %s items for user_id=%s',
                skipped_count,
                request.user.id,
            )

        return Response(
            {
                'message': f'Successfully imported {created_count} items',
                'skipped_count': skipped_count,
            }
        )
