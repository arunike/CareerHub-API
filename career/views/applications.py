from datetime import datetime

import pandas as pd
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from availability.utils import export_data

from ..models import Application, Company, Offer
from ..serializers import ApplicationExportSerializer, ApplicationSerializer


class ApplicationViewSet(viewsets.ModelViewSet):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer

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
        count, _ = Application.objects.filter(is_locked=False).delete()
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
            if file_obj.name.endswith('.csv'):
                df = pd.read_csv(file_obj)
            elif file_obj.name.endswith('.xlsx'):
                df = pd.read_excel(file_obj)
            else:
                return Response({'error': 'Unsupported file format'}, status=status.HTTP_400_BAD_REQUEST)

            created_count = 0
            for _, row in df.iterrows():
                company_name = row.get('company', row.get('Company', 'Unknown'))
                role_title = row.get('role', row.get('Role', 'Unknown Role'))
                status_val = row.get('status', row.get('Status', 'APPLIED')).upper()

                company, _ = Company.objects.get_or_create(name=company_name)
                Application.objects.create(
                    company=company,
                    role_title=role_title,
                    status=status_val,
                    job_link=row.get('link', ''),
                    salary_range=row.get('salary', ''),
                    location=row.get('location', ''),
                    date_applied=(
                        pd.to_datetime(row.get('date_applied', datetime.now())).date()
                        if 'date_applied' in row
                        else None
                    ),
                )
                created_count += 1

            return Response({'message': f'Successfully imported {created_count} applications'})
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
