from datetime import datetime

from django.conf import settings
import pandas as pd
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from availability.models import UserSettings
from availability.utils import export_data
from ..models import Application, Company
from ..serializers import ApplicationExportSerializer, ApplicationSerializer
from ..services.offers import ensure_offer_for_application
from ..services.job_board_import import extract_job_posting
from ..upload_validation import validate_import_row_count, validate_import_upload


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


class ApplicationViewSet(viewsets.ModelViewSet):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer

    def get_queryset(self):
        return Application.objects.filter(user=self.request.user).select_related('company')

    def perform_create(self, serializer):
        instance = serializer.save()
        ensure_offer_for_application(instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        ensure_offer_for_application(instance)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This application is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        count, _ = self.get_queryset().filter(is_locked=False).delete()
        return Response(
            {'message': f'Deleted {count} applications. Locked applications were preserved.'},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), ApplicationExportSerializer, fmt, 'applications')


class ImportApplicationsView(APIView):
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
