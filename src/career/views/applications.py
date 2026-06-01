import json
import re
from datetime import datetime
from types import SimpleNamespace

from django.conf import settings
from django.db.models import Q
import pandas as pd
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from availability.ai_provider import AIProviderConfigurationError, AIProviderRequestError, relay_ai_provider_chat_completion
from availability.models import UserSettings
from availability.utils import export_data
from ..models import AIArtifact, Application, ApplicationTimelineEntry, Company, Document
from ..serializers import (
    AIArtifactSerializer,
    ApplicationExportSerializer,
    ApplicationSerializer,
    ApplicationTimelineEntrySerializer,
    DocumentSerializer,
)
from ..services.offers import ensure_offer_for_application
from ..services.job_board_import import extract_job_posting
from ..services.google_sheets import _upsert_application
from ..upload_validation import validate_import_row_count, validate_import_upload

from rest_framework.pagination import PageNumberPagination
from django.core.cache import cache
from ..cache import get_applications_cache_key, invalidate_applications_cache


class ConditionalPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        if 'page' not in request.query_params:
            return None
        return super().paginate_queryset(queryset, request, view)



VISA_SPONSORSHIP_IMPORT_ALIASES = {
    'UNKNOWN': '',
    'NOT SPECIFIED': '',
    '': '',
    'SPONSORSHIP AVAILABLE': 'AVAILABLE',
    'SPONSORSHIP': 'AVAILABLE',
    'YES': 'AVAILABLE',
    'H1B': 'AVAILABLE',
    'H-1B': 'AVAILABLE',
    'TRANSFER': 'TRANSFER_ONLY',
    'TRANSFER ONLY': 'TRANSFER_ONLY',
    'H1B TRANSFER': 'TRANSFER_ONLY',
    'H-1B TRANSFER': 'TRANSFER_ONLY',
    'NO': 'NOT_AVAILABLE',
    'NONE': 'NOT_AVAILABLE',
    'NO SPONSORSHIP': 'NOT_AVAILABLE',
    'NOT NEEDED': 'NOT_NEEDED',
    'CITIZEN': 'NOT_NEEDED',
    'GC': 'NOT_NEEDED',
    'GREEN CARD': 'NOT_NEEDED',
}
DAY_ONE_GC_IMPORT_ALIASES = {
    'UNKNOWN': '',
    'NOT SPECIFIED': '',
    '': '',
    'YES': 'YES',
    'Y': 'YES',
    'TRUE': 'YES',
    'DAY 1 GC': 'YES',
    'NO': 'NO',
    'N': 'NO',
    'FALSE': 'NO',
    'N/A': 'NOT_APPLICABLE',
    'NA': 'NOT_APPLICABLE',
    'NOT APPLICABLE': 'NOT_APPLICABLE',
}

APPLICATION_IMPORT_FIELDS = [
    {'key': 'external_id', 'label': 'External ID', 'required': False},
    {'key': 'company_name', 'label': 'Company', 'required': True},
    {'key': 'role_title', 'label': 'Role', 'required': True},
    {'key': 'status', 'label': 'Status', 'required': False},
    {'key': 'job_link', 'label': 'Job Link', 'required': False},
    {'key': 'salary_range', 'label': 'Salary', 'required': False},
    {'key': 'location', 'label': 'Location', 'required': False},
    {'key': 'office_location', 'label': 'Office Location', 'required': False},
    {'key': 'date_applied', 'label': 'Date Applied', 'required': False},
    {'key': 'notes', 'label': 'Notes', 'required': False},
    {'key': 'visa_sponsorship', 'label': 'Visa Sponsorship', 'required': False},
    {'key': 'day_one_gc', 'label': 'Day 1 GC', 'required': False},
    {'key': 'growth_score', 'label': 'Growth Score', 'required': False},
    {'key': 'work_life_score', 'label': 'Work Life Score', 'required': False},
    {'key': 'brand_score', 'label': 'Brand Score', 'required': False},
    {'key': 'team_score', 'label': 'Team Score', 'required': False},
]

APPLICATION_IMPORT_ALIASES = {
    'external_id': ['external id', 'id', 'row id', 'sheet id', '编号', 'id externe'],
    'company_name': ['company', 'company name', 'employer', 'organization', '公司', '会社', '会社名', '企業', 'empresa', 'compañía', 'entreprise'],
    'role_title': ['role', 'role title', 'title', 'position', 'job title', '职位', '岗位', '職種', '役職', 'puesto', 'cargo', 'poste'],
    'status': ['status', 'stage', 'application status', '状态', '狀態', 'ステータス', 'estado', 'statut'],
    'job_link': ['link', 'job link', 'url', 'posting', 'posting url', '申请链接', '链接', '求人url', '応募リンク', 'enlace', 'lien'],
    'salary_range': ['salary', 'salary range', 'compensation', 'pay', '薪资', '薪水', '給与', '年収', 'salario', 'salaire'],
    'location': ['location', 'home location', 'city', '地点', '位置', '所在地', '勤務地', 'ubicación', 'localisation'],
    'office_location': ['office location', 'office', 'work location', '办公地点', '办公室', 'オフィス', '勤務地', 'oficina', 'bureau'],
    'date_applied': ['date applied', 'applied date', 'application date', 'applied on', '申请日期', '応募日', 'fecha solicitud', 'date candidature'],
    'notes': ['notes', 'note', 'comments', 'comment', '备注', 'メモ', 'notas', 'notes'],
    'visa_sponsorship': ['visa sponsorship', 'visa', 'sponsorship', '签证', 'ビザ', 'visado', 'visa parrainage'],
    'day_one_gc': ['day 1 gc', 'day one gc', 'green card', 'gc', '绿卡', 'グリーンカード'],
    'growth_score': ['growth score', 'growth', '成长', '成長', 'crecimiento'],
    'work_life_score': ['wlb score', 'work life score', 'work life balance', '工作生活平衡', 'ワークライフバランス'],
    'brand_score': ['brand score', 'brand', '品牌', 'ブランド'],
    'team_score': ['team score', 'manager team score', 'team', '团队', 'チーム'],
}


def _row_value(row, *names, default=None):
    for name in names:
        if name in row and pd.notna(row.get(name)):
            return row.get(name)
    return default


def _normalize_import_choice(value, valid_values, aliases, default=''):
    if value is None or pd.isna(value):
        return default
    normalized = str(value).strip().upper().replace('-', '_').replace(' ', '_')
    if normalized in valid_values:
        return normalized
    label = str(value).strip().upper()
    return aliases.get(label, default)


def _normalize_import_score(value):
    if value is None or pd.isna(value):
        return None
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return None
    return score if 1 <= score <= 5 else None


def _normalize_header(value):
    return re.sub(r'\s+', ' ', re.sub(r'[_-]+', ' ', str(value or '').strip().lower())).strip()


def _build_import_mapping(headers):
    normalized_headers = [{'raw': header, 'normalized': _normalize_header(header)} for header in headers]
    mapping = {}
    for field in APPLICATION_IMPORT_FIELDS:
        aliases = [field['key'], field['label'], *APPLICATION_IMPORT_ALIASES.get(field['key'], [])]
        normalized_aliases = {_normalize_header(alias) for alias in aliases}
        match = next(
            (
                header
                for header in normalized_headers
                if header['normalized'] in normalized_aliases
            ),
            None,
        )
        if not match:
            match = next(
                (
                    header
                    for header in normalized_headers
                    if any(alias and (alias in header['normalized'] or header['normalized'] in alias) for alias in normalized_aliases)
                ),
                None,
            )
        if match:
            mapping[field['key']] = match['raw']
    return mapping


def _dataframe_to_records(df):
    clean_df = df.where(pd.notna(df), '')
    return [
        {str(key): str(value).strip() if value is not None else '' for key, value in row.items()}
        for row in clean_df.to_dict(orient='records')
    ]


def _has_ai_provider_config(user_settings):
    return bool(
        getattr(user_settings, 'ai_provider_endpoint', '')
        and getattr(user_settings, 'ai_provider_model', '')
        and user_settings.has_ai_provider_api_key()
    )


def _infer_import_mapping_with_ai(user_settings, headers, sample_rows, baseline_mapping):
    if not _has_ai_provider_config(user_settings):
        return baseline_mapping, 'not_configured', 'AI provider is not configured. Used built-in header matching.'
    try:
        response = relay_ai_provider_chat_completion(
            user_settings=user_settings,
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'Map spreadsheet columns to CareerHub application import fields. '
                        'Headers may be synonyms or different languages. Return only JSON. '
                        'Use canonical field keys as object keys and original header names as values. '
                        'Only map a field when the header is clearly represented.'
                    ),
                },
                {
                    'role': 'user',
                    'content': json.dumps(
                        {
                            'canonical_fields': APPLICATION_IMPORT_FIELDS,
                            'headers': headers,
                            'sample_rows': sample_rows[:5],
                            'baseline_mapping': baseline_mapping,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.1,
        )
        content = response['choices'][0]['message']['content']
        normalized = (content or '').strip()
        if normalized.startswith('```'):
            normalized = re.sub(r'^```(?:json)?\s*', '', normalized, flags=re.IGNORECASE)
            normalized = re.sub(r'\s*```$', '', normalized)
        parsed = json.loads(normalized)
        if not isinstance(parsed, dict):
            raise ValueError('AI provider returned a non-object mapping.')
        valid_headers = set(headers)
        valid_fields = {field['key'] for field in APPLICATION_IMPORT_FIELDS}
        ai_mapping = {
            str(field): str(header)
            for field, header in parsed.items()
            if field in valid_fields and header in valid_headers
        }
        return {**baseline_mapping, **ai_mapping}, 'success', 'AI suggested the column mapping.'
    except (AIProviderConfigurationError, AIProviderRequestError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return baseline_mapping, 'failed', f'AI mapping failed. Used built-in header matching. {str(exc)[:160]}'


def _row_to_application_payload(row, mapping):
    payload = {}
    for field, header in (mapping or {}).items():
        if not header:
            continue
        value = row.get(header, '')
        if value is None:
            value = ''
        if field in {'visa_sponsorship', 'day_one_gc', 'growth_score', 'work_life_score', 'brand_score', 'team_score'}:
            continue
        payload[field] = str(value).strip()
    return payload


def _apply_extra_import_fields(application, row, mapping):
    updates = []
    visa_sponsorship = _normalize_import_choice(
        row.get(mapping.get('visa_sponsorship')),
        {choice[0] for choice in Application.VISA_SPONSORSHIP_CHOICES},
        VISA_SPONSORSHIP_IMPORT_ALIASES,
    )
    day_one_gc = _normalize_import_choice(
        row.get(mapping.get('day_one_gc')),
        {choice[0] for choice in Application.DAY_ONE_GC_CHOICES},
        DAY_ONE_GC_IMPORT_ALIASES,
    )
    score_fields = {
        'growth_score': _normalize_import_score(row.get(mapping.get('growth_score'))),
        'work_life_score': _normalize_import_score(row.get(mapping.get('work_life_score'))),
        'brand_score': _normalize_import_score(row.get(mapping.get('brand_score'))),
        'team_score': _normalize_import_score(row.get(mapping.get('team_score'))),
    }
    for field, value in {'visa_sponsorship': visa_sponsorship, 'day_one_gc': day_one_gc, **score_fields}.items():
        if field in mapping and getattr(application, field) != value:
            setattr(application, field, value)
            updates.append(field)
    if updates:
        application.save(update_fields=[*updates, 'updated_at'])


def _preview_import_rows(user, rows, mapping):
    items = []
    for index, row in enumerate(rows, start=2):
        payload = _row_to_application_payload(row, mapping)
        company_name = payload.get('company_name') or ''
        role_title = payload.get('role_title') or ''
        action = 'error'
        detail = ''
        local_object_id = None
        if not company_name or not role_title:
            detail = 'Company and role are required.'
        else:
            company = Company.objects.filter(user=user, name=company_name).first()
            application = Application.objects.filter(user=user, company=company, role_title=role_title).order_by('id').first() if company else None
            if application:
                local_object_id = application.id
                action = 'update'
                detail = 'Matches an existing application by company and role.'
            else:
                action = 'create'
                detail = 'New application.'
        items.append({
            'row': index,
            'action': action,
            'detail': detail,
            'company_name': company_name,
            'role_title': role_title,
            'status': payload.get('status') or 'APPLIED',
            'local_object_id': local_object_id,
            'raw': row,
        })
    return items


class ApplicationViewSet(viewsets.ModelViewSet):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer
    pagination_class = ConditionalPageNumberPagination

    def list(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = get_applications_cache_key(user_id, "list", request.query_params)
        
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)
            
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            cache.set(cache_key, response.data, timeout=300)
            return response
            
        serializer = self.get_serializer(queryset, many=True)
        response_data = serializer.data
        cache.set(cache_key, response_data, timeout=300)
        return Response(response_data)


    def get_queryset(self):
        return Application.objects.filter(user=self.request.user).select_related('company')

    def perform_create(self, serializer):
        instance = serializer.save()
        ensure_offer_for_application(instance)
        invalidate_applications_cache(self.request.user.id)

    def perform_update(self, serializer):
        instance = serializer.save()
        ensure_offer_for_application(instance)
        invalidate_applications_cache(self.request.user.id)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This application is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        response = super().destroy(request, *args, **kwargs)
        invalidate_applications_cache(request.user.id)
        return response

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        count, _ = self.get_queryset().filter(is_locked=False).delete()
        invalidate_applications_cache(request.user.id)
        return Response(
            {'message': f'Deleted {count} applications. Locked applications were preserved.'},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), ApplicationExportSerializer, fmt, 'applications')

    @action(detail=True, methods=['get'])
    def prep_workspace(self, request, pk=None):
        application = self.get_object()
        artifact_match = (
            Q(source_application=application)
            | Q(payload__applicationId=application.id)
            | Q(payload__applicationId=str(application.id))
        )
        artifacts = (
            AIArtifact.objects
            .filter(user=request.user)
            .filter(artifact_match)
            .order_by('-saved_at', '-created_at')
        )
        jd_reports = list(artifacts.filter(artifact_type=AIArtifact.TYPE_JD_REPORT)[:5])
        cover_letters = list(artifacts.filter(artifact_type=AIArtifact.TYPE_COVER_LETTER)[:5])
        documents = (
            Document.objects
            .filter(user=request.user, application=application, is_current=True)
            .order_by('-updated_at')
        )
        timeline = (
            ApplicationTimelineEntry.objects
            .filter(user=request.user, application=application)
            .prefetch_related('documents')
            .order_by('stage_order', 'event_date', 'created_at')
        )
        latest_jd_report = jd_reports[0] if jd_reports else None
        latest_payload = latest_jd_report.payload if latest_jd_report else {}

        serializer_context = {'request': request}
        return Response(
            {
                'application': ApplicationSerializer(application, context=serializer_context).data,
                'notes': application.notes or '',
                'documents': DocumentSerializer(documents, many=True, context=serializer_context).data,
                'timeline': ApplicationTimelineEntrySerializer(
                    timeline, many=True, context=serializer_context
                ).data,
                'jd_reports': AIArtifactSerializer(
                    jd_reports, many=True, context=serializer_context
                ).data,
                'cover_letters': AIArtifactSerializer(
                    cover_letters, many=True, context=serializer_context
                ).data,
                'latest_jd_report': (
                    AIArtifactSerializer(latest_jd_report, context=serializer_context).data
                    if latest_jd_report
                    else None
                ),
                'evidence': {
                    'best_experiences': latest_payload.get('best_experiences') or [],
                    'tailored_bullets': latest_payload.get('tailored_bullets') or [],
                    'matched_skills': latest_payload.get('matched_skills') or [],
                    'missing_skills': latest_payload.get('missing_skills') or [],
                },
                'readiness': {
                    'linked_documents': documents.count(),
                    'timeline_entries': timeline.count(),
                    'jd_reports': len(jd_reports),
                    'cover_letters': len(cover_letters),
                    'has_notes': bool((application.notes or '').strip()),
                    'has_job_link': bool(application.job_link),
                },
            }
        )


class ImportApplicationsView(APIView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_import_upload(
                file_obj,
                {'.csv', '.xlsx'},
                'Application import file',
            )
            if file_obj.name.endswith('.csv'):
                df = pd.read_csv(file_obj, nrows=settings.MAX_IMPORT_ROWS + 1)
            elif file_obj.name.endswith('.xlsx'):
                df = pd.read_excel(file_obj, nrows=settings.MAX_IMPORT_ROWS + 1)
            else:
                return Response({'error': 'Unsupported file format'}, status=status.HTTP_400_BAD_REQUEST)

            validate_import_row_count(len(df.index), 'Application import file')

            headers = [str(column) for column in df.columns]
            rows = _dataframe_to_records(df)
            baseline_mapping = _build_import_mapping(headers)
            user_settings, _ = UserSettings.objects.get_or_create(user=request.user)
            mapping, ai_status, ai_message = _infer_import_mapping_with_ai(
                user_settings,
                headers,
                rows[:5],
                baseline_mapping,
            )
            preview_items = _preview_import_rows(request.user, rows, mapping)
            return Response({
                'ok': True,
                'preview': {
                    'headers': headers,
                    'rows': rows,
                    'mapping': mapping,
                    'field_options': APPLICATION_IMPORT_FIELDS,
                    'items': preview_items,
                    'summary': {
                        'total_rows': len(rows),
                        'creates': sum(1 for item in preview_items if item['action'] == 'create'),
                        'updates': sum(1 for item in preview_items if item['action'] == 'update'),
                        'errors': sum(1 for item in preview_items if item['action'] == 'error'),
                    },
                    'ai_status': ai_status,
                    'ai_message': ai_message,
                },
            }, status=status.HTTP_200_OK)
        except DRFValidationError as exc:
            detail = exc.detail[0] if isinstance(exc.detail, list) else exc.detail
            return Response({'error': str(detail)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class ApplyImportApplicationsView(APIView):
    parser_classes = (JSONParser,)

    def post(self, request, *args, **kwargs):
        rows = request.data.get('rows') or []
        mapping = request.data.get('mapping') or {}
        if not isinstance(rows, list) or not isinstance(mapping, dict):
            return Response({'error': 'Rows and mapping are required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not mapping.get('company_name') or not mapping.get('role_title'):
            return Response({'error': 'Map Company and Role before importing.'}, status=status.HTTP_400_BAD_REQUEST)

        result = {'created': 0, 'updated': 0, 'errors': []}
        config = SimpleNamespace(
            user=request.user,
            target_type='APPLICATIONS',
            overwrite_strategies={},
        )
        for index, row in enumerate(rows, start=2):
            if not isinstance(row, dict):
                result['errors'].append({'row': index, 'error': 'Row is not an object.'})
                continue
            payload = _row_to_application_payload(row, mapping)
            payload['_user'] = request.user
            try:
                company_name = payload.get('company_name') or ''
                role_title = payload.get('role_title') or ''
                company = Company.objects.filter(user=request.user, name=company_name).first()
                existing = (
                    Application.objects.filter(user=request.user, company=company, role_title=role_title)
                    .order_by('id')
                    .first()
                    if company and role_title
                    else None
                )
                tracked = SimpleNamespace(local_object_id=existing.id, created_at=existing.created_at) if existing else None
                application, created, _diff = _upsert_application(config, payload, tracked=tracked)
                _apply_extra_import_fields(application, row, mapping)
                ensure_offer_for_application(application)
                result['created' if created else 'updated'] += 1
            except Exception as exc:
                result['errors'].append({'row': index, 'error': str(exc)})

        return Response({'ok': not result['errors'], 'result': result}, status=status.HTTP_200_OK)


class LegacyImportApplicationsView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_import_upload(
                file_obj,
                {'.csv', '.xlsx'},
                'Application import file',
            )
            if file_obj.name.endswith('.csv'):
                df = pd.read_csv(file_obj, nrows=settings.MAX_IMPORT_ROWS + 1)
            elif file_obj.name.endswith('.xlsx'):
                df = pd.read_excel(file_obj, nrows=settings.MAX_IMPORT_ROWS + 1)
            else:
                return Response({'error': 'Unsupported file format'}, status=status.HTTP_400_BAD_REQUEST)

            validate_import_row_count(len(df.index), 'Application import file')

            created_count = 0
            for _, row in df.iterrows():
                company_name = row.get('company', row.get('Company', 'Unknown'))
                role_title = row.get('role', row.get('Role', 'Unknown Role'))
                status_val = row.get('status', row.get('Status', 'APPLIED')).upper()

                company, _ = Company.objects.get_or_create(user=request.user, name=company_name)
                Application.objects.create(
                    user=request.user,
                    company=company,
                    role_title=role_title,
                    status=status_val,
                    job_link=row.get('link', ''),
                    salary_range=row.get('salary', ''),
                    location=row.get('home_location', row.get('location', '')),
                    office_location=row.get('office_location', row.get('Office Location', '')),
                    visa_sponsorship=_normalize_import_choice(
                        _row_value(row, 'visa_sponsorship', 'Visa Sponsorship'),
                        {choice[0] for choice in Application.VISA_SPONSORSHIP_CHOICES},
                        VISA_SPONSORSHIP_IMPORT_ALIASES,
                    ),
                    day_one_gc=_normalize_import_choice(
                        _row_value(row, 'day_one_gc', 'Day 1 GC', 'Day One GC'),
                        {choice[0] for choice in Application.DAY_ONE_GC_CHOICES},
                        DAY_ONE_GC_IMPORT_ALIASES,
                    ),
                    growth_score=_normalize_import_score(_row_value(row, 'growth_score', 'Growth Score')),
                    work_life_score=_normalize_import_score(
                        _row_value(row, 'work_life_score', 'WLB Score', 'Work Life Score')
                    ),
                    brand_score=_normalize_import_score(_row_value(row, 'brand_score', 'Brand Score')),
                    team_score=_normalize_import_score(_row_value(row, 'team_score', 'Team Score', 'Manager Team Score')),
                    date_applied=(
                        pd.to_datetime(row.get('date_applied', datetime.now())).date()
                        if 'date_applied' in row
                        else None
                    ),
                )
                created_count += 1

            return Response({'message': f'Successfully imported {created_count} applications'})
        except DRFValidationError as exc:
            detail = exc.detail[0] if isinstance(exc.detail, list) else exc.detail
            return Response({'error': str(detail)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class JobBoardImportView(APIView):
    def post(self, request, *args, **kwargs):
        url = request.data.get('url', '')
        try:
            user_settings, _ = UserSettings.objects.get_or_create(user=request.user)
            return Response(
                extract_job_posting(url, user_settings=user_settings),
                status=status.HTTP_200_OK,
            )
        except DRFValidationError as exc:
            detail = exc.detail[0] if isinstance(exc.detail, list) else exc.detail
            return Response({'error': str(detail)}, status=status.HTTP_400_BAD_REQUEST)
