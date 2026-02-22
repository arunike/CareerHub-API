from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Company, Application, Offer, Document, Task
from .serializers import CompanySerializer, ApplicationSerializer, ApplicationExportSerializer, OfferSerializer, DocumentSerializer, DocumentExportSerializer, TaskSerializer
from availability.utils import export_data
from datetime import datetime
from django.db.models import Q, Max
from django.db import transaction
from rest_framework.parsers import MultiPartParser, FormParser

class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer

class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

    def get_queryset(self):
        qs = Document.objects.all().order_by('-updated_at')
        include_versions = self.request.query_params.get('include_versions')
        if include_versions in ('1', 'true', 'True'):
            return qs
        return qs.filter(is_current=True)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {"error": "This document is locked and cannot be deleted. Unlock it first."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(is_current=True, version_number=1, root_document=None)

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        count, _ = Document.objects.filter(is_locked=False).delete()
        return Response(
            {"message": f"Deleted {count} documents. Locked documents were preserved."},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), DocumentExportSerializer, fmt, 'documents')

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        doc = self.get_object()
        root = doc.root_document or doc
        versions = Document.objects.filter(Q(id=root.id) | Q(root_document_id=root.id)).order_by('-version_number')
        serializer = self.get_serializer(versions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def add_version(self, request, pk=None):
        doc = self.get_object()
        root = doc.root_document or doc
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            current_versions = Document.objects.filter(Q(id=root.id) | Q(root_document_id=root.id))
            max_version = current_versions.aggregate(max_v=Max('version_number'))['max_v'] or 1
            current_versions.update(is_current=False)

            new_doc = Document.objects.create(
                title=request.data.get('title', doc.title),
                file=file_obj,
                document_type=request.data.get('document_type', doc.document_type),
                application_id=request.data.get('application') if request.data.get('application') not in (None, '', 'null') else doc.application_id,
                root_document=root,
                version_number=max_version + 1,
                is_current=True,
                is_locked=False,
            )

        serializer = self.get_serializer(new_doc)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

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
                is_current=False
            )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {"error": "This application is locked and cannot be deleted. Unlock it first."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        # Only delete unlocked applications
        count, _ = Application.objects.filter(is_locked=False).delete()
        return Response(
            {"message": f"Deleted {count} applications. Locked applications were preserved."},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), ApplicationExportSerializer, fmt, 'applications')

from rest_framework.views import APIView
import pandas as pd

class ImportApplicationsView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if file_obj.name.endswith('.csv'):
                df = pd.read_csv(file_obj)
            elif file_obj.name.endswith('.xlsx'):
                df = pd.read_excel(file_obj)
            else:
                return Response({"error": "Unsupported file format"}, status=status.HTTP_400_BAD_REQUEST)
            
            created_count = 0
            for _, row in df.iterrows():
                # Basic mapping - adjust based on actual columns
                company_name = row.get('company', row.get('Company', 'Unknown'))
                role_title = row.get('role', row.get('Role', 'Unknown Role'))
                status_val = row.get('status', row.get('Status', 'APPLIED')).upper()
                
                company, _ = Company.objects.get_or_create(name=company_name)
                
                Application.objects.create(
                    company=company,
                    role_title=role_title,
                    status=status_val,
                    # Add other fields as best effort
                    job_link=row.get('link', ''),
                    salary_range=row.get('salary', ''),
                    location=row.get('location', ''),
                    date_applied=pd.to_datetime(row.get('date_applied', datetime.now())).date() if 'date_applied' in row else None
                )
                created_count += 1
                
            return Response({"message": f"Successfully imported {created_count} applications"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class OfferViewSet(viewsets.ModelViewSet):
    queryset = Offer.objects.all()
    serializer_class = OfferSerializer


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all().order_by('status', 'position', '-updated_at')
    serializer_class = TaskSerializer

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        updates = request.data.get('updates', [])
        if not isinstance(updates, list):
            return Response({"error": "updates must be a list"}, status=status.HTTP_400_BAD_REQUEST)

        for item in updates:
            task_id = item.get('id')
            if task_id is None:
                continue
            Task.objects.filter(id=task_id).update(
                status=item.get('status', 'TODO'),
                position=item.get('position', 0),
            )
        return Response({"message": "Tasks reordered successfully"}, status=status.HTTP_200_OK)
