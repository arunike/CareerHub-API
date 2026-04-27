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

from career.models import Application, ApplicationTimelineEntry, Company, Document, Experience, Offer, Task
from career.serializers import (
    ApplicationExportSerializer,
    DocumentExportSerializer,
    ExperienceExportSerializer,
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
                        timezone='PT',
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


class EventCategoryViewSet(viewsets.ModelViewSet):
    queryset = EventCategory.objects.all()
    serializer_class = EventCategorySerializer

    def get_queryset(self):
        return EventCategory.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class UserSettingsViewSet(viewsets.ModelViewSet):
    queryset = UserSettings.objects.all()
    serializer_class = UserSettingsSerializer

    def get_queryset(self):
        return UserSettings.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['get', 'put'])
    def current(self, request):
        settings, _ = UserSettings.objects.get_or_create(user=request.user)
        if request.method == 'GET':
            return Response(self.get_serializer(settings).data)

        serializer = self.get_serializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def export_all(self, request):
        fmt = request.query_params.get('fmt', 'json')
        data_map = {
            'events': (Event.objects.filter(user=request.user), EventSerializer),
            'holidays': (CustomHoliday.objects.filter(user=request.user), CustomHolidaySerializer),
            'applications': (Application.objects.filter(user=request.user), ApplicationExportSerializer),
            'user_settings': (UserSettings.objects.filter(user=request.user), UserSettingsSerializer),
            'categories': (EventCategory.objects.filter(user=request.user), EventCategorySerializer),
        }

        if fmt in {'xlsx', 'excel'}:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                for name, (queryset, serializer_cls) in data_map.items():
                    data = serializer_cls(queryset, many=True).data
                    df = pd.DataFrame(data) if data else pd.DataFrame()
                    df.to_excel(writer, sheet_name=name[:31], index=False)
            response = HttpResponse(
                buffer.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = (
                f'attachment; filename="availability_manager_export_{datetime.now().strftime("%Y%m%d")}.xlsx"'
            )
            return response

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for name, (queryset, serializer_cls) in data_map.items():
                data = serializer_cls(queryset, many=True).data
                if fmt == 'csv':
                    df = pd.DataFrame(data) if data else pd.DataFrame()
                    csv_buffer = io.StringIO()
                    df.to_csv(csv_buffer, index=False)
                    zip_file.writestr(f'{name}.csv', csv_buffer.getvalue())
                else:
                    zip_file.writestr(f'{name}.json', json.dumps(data, indent=2, default=str))

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        response = HttpResponse(buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="availability_manager_backup_{timestamp}.zip"'
        return response

    def _build_account_export_payload(self, request):
        user = request.user
        serializer_context = {'request': request}
        return {
            'schema': 'careerhub.account_export.v1',
            'exported_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
            'account': {
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'full_name': getattr(user, 'full_name', '') or f'{user.first_name} {user.last_name}'.strip(),
            },
            'availability': {
                'user_settings': UserSettingsSerializer(
                    UserSettings.objects.filter(user=user), many=True, context=serializer_context
                ).data,
                'categories': EventCategorySerializer(EventCategory.objects.filter(user=user), many=True).data,
                'events': EventSerializer(Event.objects.filter(user=user), many=True, context=serializer_context).data,
                'holidays': CustomHolidaySerializer(CustomHoliday.objects.filter(user=user), many=True).data,
                'availability_overrides': AvailabilityOverrideSerializer(
                    AvailabilityOverride.objects.filter(user=user), many=True
                ).data,
                'availability_settings': AvailabilitySettingSerializer(
                    AvailabilitySetting.objects.filter(user=user), many=True
                ).data,
                'share_links': ShareLinkSerializer(ShareLink.objects.filter(user=user), many=True).data,
                'public_bookings': PublicBookingSerializer(
                    PublicBooking.objects.filter(share_link__user=user), many=True
                ).data,
            },
            'career': {
                'companies': [_model_payload(company) for company in Company.objects.filter(user=user)],
                'applications': ApplicationExportSerializer(Application.objects.filter(user=user), many=True).data,
                'offers': OfferExportSerializer(Offer.objects.filter(application__user=user), many=True).data,
                'documents': DocumentExportSerializer(
                    Document.objects.filter(user=user), many=True, context=serializer_context
                ).data,
                'tasks': TaskSerializer(Task.objects.filter(user=user), many=True).data,
                'experiences': ExperienceExportSerializer(Experience.objects.filter(user=user), many=True).data,
                'application_timeline': [
                    {
                        **_model_payload(entry, exclude=('documents',)),
                        'application_role': entry.application.role_title,
                        'application_company': entry.application.company.name,
                        'documents': list(entry.documents.filter(user=user).values_list('title', flat=True)),
                    }
                    for entry in ApplicationTimelineEntry.objects.filter(user=user).select_related(
                        'application', 'application__company'
                    )
                ],
            },
        }

    @action(detail=False, methods=['get'], url_path='account-export')
    def account_export(self, request):
        fmt = request.query_params.get('fmt', 'json')
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        payload = self._build_account_export_payload(request)
        if fmt == 'zip':
            return _zip_json_response(payload, f'careerhub_account_export_{timestamp}.zip')
        return _json_response(payload, f'careerhub_account_export_{timestamp}.json')

    @action(
        detail=False,
        methods=['post'],
        url_path='restore-backup',
        parser_classes=[MultiPartParser, FormParser],
    )
    def restore_backup(self, request):
        file_obj = request.FILES.get('file')
        restore_mode = request.data.get('mode', 'merge')
        if restore_mode not in {'merge', 'replace'}:
            return Response({'error': 'Restore mode must be merge or replace.'}, status=status.HTTP_400_BAD_REQUEST)
        if not file_obj:
            return Response({'error': 'No backup file uploaded.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if file_obj.name.lower().endswith('.zip'):
                with zipfile.ZipFile(file_obj) as zip_file:
                    json_names = [name for name in zip_file.namelist() if name.endswith('.json')]
                    if not json_names:
                        return Response({'error': 'No JSON export found in backup zip.'}, status=status.HTTP_400_BAD_REQUEST)
                    payload = json.loads(zip_file.read(json_names[0]).decode('utf-8'))
            else:
                payload = json.loads(file_obj.read().decode('utf-8'))
        except (json.JSONDecodeError, zipfile.BadZipFile, UnicodeDecodeError):
            return Response({'error': 'Backup file could not be read.'}, status=status.HTTP_400_BAD_REQUEST)

        if payload.get('schema') != 'careerhub.account_export.v1':
            return Response(
                {'error': 'Unsupported backup format. Please upload a CareerHub account export.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        availability_data = payload.get('availability') or {}
        career_data = payload.get('career') or {}
        created_counts = {
            'settings': 0,
            'categories': 0,
            'holidays': 0,
            'events': 0,
            'companies': 0,
            'applications': 0,
            'tasks': 0,
        }

        with transaction.atomic():
            if restore_mode == 'replace':
                ApplicationTimelineEntry.objects.filter(user=user).delete()
                Task.objects.filter(user=user).delete()
                Offer.objects.filter(application__user=user).delete()
                Document.objects.filter(user=user).delete()
                Experience.objects.filter(user=user).delete()
                Application.objects.filter(user=user).delete()
                Company.objects.filter(user=user).delete()
                PublicBooking.objects.filter(share_link__user=user).delete()
                ShareLink.objects.filter(user=user).delete()
                AvailabilityOverride.objects.filter(user=user).delete()
                AvailabilitySetting.objects.filter(user=user).delete()
                Event.objects.filter(user=user).delete()
                CustomHoliday.objects.filter(user=user).delete()
                EventCategory.objects.filter(user=user).delete()

            settings_items = availability_data.get('user_settings') or []
            if settings_items:
                settings_payload = dict(settings_items[0])
                for field in ('id', 'email', 'profile_picture', 'ai_provider_api_key_masked', 'ai_provider_api_key_configured'):
                    settings_payload.pop(field, None)
                settings_obj, _ = UserSettings.objects.get_or_create(user=user)
                serializer = UserSettingsSerializer(settings_obj, data=settings_payload, partial=True, context={'request': request})
                serializer.is_valid(raise_exception=True)
                serializer.save()
                created_counts['settings'] = 1

            category_map = {}
            for item in availability_data.get('categories') or []:
                payload_item = {key: item.get(key) for key in ('name', 'color', 'icon', 'is_locked')}
                category, created = EventCategory.objects.update_or_create(
                    user=user,
                    name=payload_item['name'],
                    defaults=payload_item,
                )
                category_map[item.get('id')] = category
                if created:
                    created_counts['categories'] += 1

            for item in availability_data.get('holidays') or []:
                payload_item = {
                    key: item.get(key)
                    for key in ('date', 'group_id', 'description', 'holiday_type', 'is_recurring', 'is_locked', 'tab')
                }
                _, created = CustomHoliday.objects.get_or_create(
                    user=user,
                    date=payload_item['date'],
                    description=payload_item.get('description') or '',
                    defaults=payload_item,
                )
                if created:
                    created_counts['holidays'] += 1

            for item in availability_data.get('events') or []:
                payload_item = {
                    key: item.get(key)
                    for key in (
                        'name',
                        'date',
                        'start_time',
                        'end_time',
                        'timezone',
                        'color',
                        'location_type',
                        'location',
                        'meeting_link',
                        'is_recurring',
                        'recurrence_rule',
                        'notes',
                        'reminder_minutes',
                        'is_locked',
                    )
                }
                payload_item['category'] = category_map.get(item.get('category'))
                _, created = Event.objects.get_or_create(
                    user=user,
                    name=payload_item['name'],
                    date=payload_item['date'],
                    start_time=payload_item['start_time'],
                    defaults=payload_item,
                )
                if created:
                    created_counts['events'] += 1

            company_map = {}
            for item in career_data.get('companies') or []:
                company, created = Company.objects.update_or_create(
                    user=user,
                    name=item.get('name') or 'Imported Company',
                    defaults={
                        'website': item.get('website') or None,
                        'industry': item.get('industry') or '',
                    },
                )
                company_map[company.name] = company
                if created:
                    created_counts['companies'] += 1

            for item in career_data.get('applications') or []:
                company_name = item.get('company') or 'Imported Company'
                company = company_map.get(company_name)
                if not company:
                    company, created_company = Company.objects.get_or_create(user=user, name=company_name)
                    company_map[company_name] = company
                    if created_company:
                        created_counts['companies'] += 1
                defaults = {
                    key: item.get(key)
                    for key in (
                        'status',
                        'rto_policy',
                        'rto_days_per_week',
                        'commute_cost_value',
                        'commute_cost_frequency',
                        'free_food_perk_value',
                        'free_food_perk_frequency',
                        'tax_base_rate',
                        'tax_bonus_rate',
                        'tax_equity_rate',
                        'monthly_rent_override',
                        'current_round',
                        'job_link',
                        'salary_range',
                        'location',
                        'office_location',
                        'visa_sponsorship',
                        'day_one_gc',
                        'growth_score',
                        'work_life_score',
                        'brand_score',
                        'team_score',
                        'notes',
                        'date_applied',
                    )
                }
                _, created = Application.objects.update_or_create(
                    user=user,
                    company=company,
                    role_title=item.get('role_title') or 'Imported Role',
                    defaults=defaults,
                )
                if created:
                    created_counts['applications'] += 1

            for item in career_data.get('tasks') or []:
                payload_item = {key: item.get(key) for key in ('title', 'description', 'status', 'priority', 'due_date', 'position')}
                _, created = Task.objects.get_or_create(
                    user=user,
                    title=payload_item.get('title') or 'Imported Task',
                    defaults=payload_item,
                )
                if created:
                    created_counts['tasks'] += 1

        return Response(
            {
                'message': 'Backup restore completed.',
                'mode': restore_mode,
                'created_counts': created_counts,
                'note': 'Restore imports core account, settings, schedule, application, and task records. Document files and public booking reservations are preserved in exports but not recreated by restore.',
            }
        )

    @action(detail=False, methods=['delete'], url_path='account')
    def delete_account(self, request):
        if request.data.get('confirm') != 'DELETE':
            return Response({'error': 'Type DELETE to confirm account deletion.'}, status=status.HTTP_400_BAD_REQUEST)

        user_settings, _ = UserSettings.objects.get_or_create(user=request.user)
        requested_at = timezone.now()
        user_settings.schedule_account_deletion(requested_at=requested_at)
        user_settings.save(update_fields=[
            'account_deletion_requested_at',
            'account_deletion_scheduled_for',
            'updated_at',
        ])

        return Response(
            {
                'message': 'Account deletion scheduled.',
                'grace_days': UserSettings.ACCOUNT_DELETION_GRACE_DAYS,
                'account_deletion_requested_at': user_settings.account_deletion_requested_at,
                'account_deletion_scheduled_for': user_settings.account_deletion_scheduled_for,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=False,
        methods=['post'],
        url_path='ai-provider/chat-completions',
        throttle_classes=[AIProviderRelayThrottle],
    )
    def ai_provider_chat_completions(self, request):
        user_settings, _ = UserSettings.objects.get_or_create(user=request.user)
        serializer = AIProviderChatCompletionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payload = relay_ai_provider_chat_completion(
                user_settings=user_settings,
                messages=serializer.validated_data['messages'],
                temperature=serializer.validated_data.get('temperature', 0.2),
            )
        except AIProviderConfigurationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except AIProviderRequestError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(payload)


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
