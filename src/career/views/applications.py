from datetime import datetime
from types import SimpleNamespace

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
import pandas as pd
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from availability.models import UserSettings
from availability.utils import export_data
from ..models import AIArtifact, Application, ApplicationTimelineEntry, Company, Document
from ..serializers import (
    NON_INTERVIEW_STAGES,
    AIArtifactSerializer,
    ApplicationExportSerializer,
    ApplicationSerializer,
    ApplicationTimelineEntrySerializer,
    DocumentSerializer,
)
from ..services.offers import ensure_offer_for_application
from ..services.job_board_import import extract_job_posting
from ..services.google_sheets import _upsert_application
from ..services.application_imports import (
    APPLICATION_IMPORT_FIELDS,
    DAY_ONE_GC_IMPORT_ALIASES,
    VISA_SPONSORSHIP_IMPORT_ALIASES,
    apply_extra_import_fields,
    build_import_mapping,
    dataframe_to_records,
    infer_import_mapping_with_ai,
    normalize_import_choice,
    normalize_import_score,
    preview_import_rows,
    row_to_application_payload,
    row_value,
)
from ..services.application_listing import (
    OFFER_RECEIVED_FILTER,
    apply_application_ordering,
    build_application_summary,
)
from ..upload_validation import validate_import_row_count, validate_import_upload

from availability.pagination import ConditionalPageNumberPagination
from ..cache import invalidate_applications_cache



class ApplicationViewSet(viewsets.ModelViewSet):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer
    pagination_class = ConditionalPageNumberPagination

    def get_queryset(self):
        # Annotated once for the whole page rather than a query per row.
        reached_interview = Exists(
            ApplicationTimelineEntry.objects.filter(application=OuterRef('pk')).exclude(
                stage__in=NON_INTERVIEW_STAGES
            )
        )
        queryset = (
            Application.objects.filter(user=self.request.user)
            # ApplicationSerializer nests the offer and lists submitted documents, and the
            # offer nests its experiences. Without these three, a list of 808 applications
            # issued 1623 queries — two per row — instead of a handful.
            .select_related('company', 'offer')
            .prefetch_related('submitted_documents', 'offer__experiences')
            .annotate(reached_interview_annotation=reached_interview)
        )
        params = self.request.query_params

        ids_filter = params.get('ids')
        if ids_filter:
            try:
                ids = [int(id_str) for id_str in ids_filter.split(',') if id_str.strip().isdigit()]
                queryset = queryset.filter(id__in=ids)
            except ValueError:
                pass

        search = (params.get('search') or '').strip()
        filters = {}
        status_filter = (params.get('status') or '').strip()
        if status_filter and status_filter != 'ALL':
            filters['status'] = status_filter

        employment_type_filter = (params.get('employment_type') or '').strip()
        if employment_type_filter and employment_type_filter != 'ALL':
            filters['employment_type'] = employment_type_filter

        location_filter = (params.get('location') or '').strip()
        if location_filter and location_filter != 'ALL':
            filters['location'] = location_filter

        year_filter = (params.get('year') or '').strip()
        if year_filter and year_filter != 'all':
            try:
                filters['year'] = int(year_filter)
            except ValueError:
                return queryset.none()

        if search:
            search_filter = Q()
            for term in search.split():
                search_filter &= (
                    Q(company__name__icontains=term)
                    | Q(role_title__icontains=term)
                    | Q(location__icontains=term)
                    | Q(office_location__icontains=term)
                    | Q(notes__icontains=term)
                )
            queryset = queryset.filter(search_filter)

        if 'status' in filters:
            if filters['status'] == 'INTERVIEWS':
                queryset = queryset.filter(
                    Q(status='SCREEN')
                    | Q(status='FINAL_ROUND')
                    | Q(status='ONSITE')
                    | Q(status__startswith='ROUND_')
                )
            elif filters['status'] == 'OFFER':
                queryset = queryset.filter(OFFER_RECEIVED_FILTER)
            else:
                queryset = queryset.filter(status=filters['status'])

        if 'employment_type' in filters:
            queryset = queryset.filter(employment_type=filters['employment_type'])

        if 'location' in filters:
            queryset = queryset.filter(
                Q(office_location__icontains=filters['location']) | Q(location__icontains=filters['location'])
            )

        if 'year' in filters:
            queryset = queryset.filter(date_applied__year=filters['year'])

        is_locked_filter = params.get('is_locked')
        if is_locked_filter:
            if is_locked_filter.lower() == 'true':
                queryset = queryset.filter(is_locked=True)
            elif is_locked_filter.lower() == 'false':
                queryset = queryset.filter(is_locked=False)

        return apply_application_ordering(queryset, params.get('ordering'))

    def get_summary_queryset(self, request):
        queryset = Application.objects.filter(user=request.user).select_related('company')
        params = request.query_params

        ids_filter = params.get('ids')
        if ids_filter:
            try:
                ids = [int(id_str) for id_str in ids_filter.split(',') if id_str.strip().isdigit()]
                queryset = queryset.filter(id__in=ids)
            except ValueError:
                pass

        search = (params.get('search') or '').strip()
        filters = {}
        employment_type_filter = (params.get('employment_type') or '').strip()
        if employment_type_filter and employment_type_filter != 'ALL':
            filters['employment_type'] = employment_type_filter

        location_filter = (params.get('location') or '').strip()
        if location_filter and location_filter != 'ALL':
            filters['location'] = location_filter

        year_filter = (params.get('year') or '').strip()
        if year_filter and year_filter != 'all':
            try:
                filters['year'] = int(year_filter)
            except ValueError:
                return queryset.none()

        if search:
            search_filter = Q()
            for term in search.split():
                search_filter &= (
                    Q(company__name__icontains=term)
                    | Q(role_title__icontains=term)
                    | Q(location__icontains=term)
                    | Q(office_location__icontains=term)
                    | Q(notes__icontains=term)
                )
            queryset = queryset.filter(search_filter)

        if 'employment_type' in filters:
            queryset = queryset.filter(employment_type=filters['employment_type'])

        if 'location' in filters:
            queryset = queryset.filter(
                Q(office_location__icontains=filters['location']) | Q(location__icontains=filters['location'])
            )

        if 'year' in filters:
            queryset = queryset.filter(date_applied__year=filters['year'])

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        summary_queryset = self.get_summary_queryset(request)
        summary = build_application_summary(summary_queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['summary'] = summary
            return response

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

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
    def options(self, request):
        queryset = Application.objects.filter(user=request.user).select_related('company', 'offer')

        # Resolving specific ids: a value already saved on a record may sit on any page, so
        # the picker asks for it directly rather than paging until it appears.
        raw_ids = (request.query_params.get('ids') or '').strip()
        if raw_ids:
            wanted = [int(part) for part in raw_ids.split(',') if part.strip().isdigit()]
            queryset = queryset.filter(id__in=wanted[:100])
            return Response([self._application_option(a) for a in queryset])

        search = (request.query_params.get('search') or '').strip()
        if search:
            search_filter = Q()
            for term in search.split():
                search_filter &= (
                    Q(company__name__icontains=term)
                    | Q(role_title__icontains=term)
                    | Q(location__icontains=term)
                )
            queryset = queryset.filter(search_filter)

        try:
            page_size = int(request.query_params.get('page_size') or 50)
        except ValueError:
            page_size = 50
        page_size = max(1, min(page_size, 200))

        try:
            page = int(request.query_params.get('page') or 1)
        except ValueError:
            page = 1
        page = max(1, page)
        start = (page - 1) * page_size

        page_items = queryset.order_by('-date_applied', '-created_at', '-id')[
            start:start + page_size
        ]
        return Response([self._application_option(a) for a in page_items])

    @staticmethod
    def _application_option(application):
        return {
            'id': application.id,
            'role_title': application.role_title,
            'status': application.status,
            'company_details': {
                'id': application.company_id,
                'name': application.company.name,
            },
            'has_offer': hasattr(application, 'offer'),
        }

    @action(detail=False, methods=['get'], url_path='company-list')
    def company_list(self, request):
        companies = (
            Company.objects.filter(user=request.user, applications__user=request.user)
            .distinct()
            .order_by('name')
            .values('id', 'name')
        )
        return Response(list(companies))

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
            .filter(
                user=request.user,
                application=application,
                deleted_by_user_at__isnull=True,
                hidden_by_sync_at__isnull=True,
            )
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
            rows = dataframe_to_records(df)
            baseline_mapping = build_import_mapping(headers)
            user_settings, _ = UserSettings.objects.get_or_create(user=request.user)
            mapping, ai_status, ai_message = infer_import_mapping_with_ai(
                user_settings,
                headers,
                rows[:5],
                baseline_mapping,
            )
            preview_items = preview_import_rows(request.user, rows, mapping)
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
            payload = row_to_application_payload(row, mapping)
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
                apply_extra_import_fields(application, row, mapping)
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
                    visa_sponsorship=normalize_import_choice(
                        row_value(row, 'visa_sponsorship', 'Visa Sponsorship'),
                        {choice[0] for choice in Application.VISA_SPONSORSHIP_CHOICES},
                        VISA_SPONSORSHIP_IMPORT_ALIASES,
                    ),
                    day_one_gc=normalize_import_choice(
                        row_value(row, 'day_one_gc', 'Day 1 GC', 'Day One GC'),
                        {choice[0] for choice in Application.DAY_ONE_GC_CHOICES},
                        DAY_ONE_GC_IMPORT_ALIASES,
                    ),
                    growth_score=normalize_import_score(row_value(row, 'growth_score', 'Growth Score')),
                    work_life_score=normalize_import_score(
                        row_value(row, 'work_life_score', 'WLB Score', 'Work Life Score')
                    ),
                    brand_score=normalize_import_score(row_value(row, 'brand_score', 'Brand Score')),
                    team_score=normalize_import_score(row_value(row, 'team_score', 'Team Score', 'Manager Team Score')),
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
