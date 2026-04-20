from datetime import datetime

from django.conf import settings
import pandas as pd
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from availability.utils import export_data
from ..models import Application, Company, Offer
from ..serializers import ApplicationExportSerializer, ApplicationSerializer
from ..upload_validation import validate_import_row_count, validate_import_upload


class ApplicationViewSet(viewsets.ModelViewSet):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer

    def get_queryset(self):
        return Application.objects.filter(user=self.request.user).select_related('company')

    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.status == 'OFFER' and not hasattr(instance, 'offer'):
            Offer.objects.create(
                application=instance,
                base_salary=0,
                bonus=0,
                equity=0,
                sign_on=0,
                benefits_value=0,
                pto_days=15,
                is_unlimited_pto=False,
                is_current=False,
            )

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
