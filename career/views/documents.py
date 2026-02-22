from django.db import transaction
from django.db.models import Max, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from availability.utils import export_data

from ..models import Document
from ..serializers import DocumentExportSerializer, DocumentSerializer


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

    def get_queryset(self):
        queryset = Document.objects.all().order_by('-updated_at')
        include_versions = self.request.query_params.get('include_versions')
        if include_versions in ('1', 'true', 'True'):
            return queryset
        return queryset.filter(is_current=True)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This document is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(is_current=True, version_number=1, root_document=None)

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        count, _ = Document.objects.filter(is_locked=False).delete()
        return Response(
            {'message': f'Deleted {count} documents. Locked documents were preserved.'},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), DocumentExportSerializer, fmt, 'documents')

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        doc = self.get_object()
        root = doc.root_document or doc
        versions = Document.objects.filter(Q(id=root.id) | Q(root_document_id=root.id)).order_by(
            '-version_number'
        )
        serializer = self.get_serializer(versions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def add_version(self, request, pk=None):
        doc = self.get_object()
        root = doc.root_document or doc
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            current_versions = Document.objects.filter(Q(id=root.id) | Q(root_document_id=root.id))
            max_version = current_versions.aggregate(max_v=Max('version_number'))['max_v'] or 1
            current_versions.update(is_current=False)

            new_doc = Document.objects.create(
                title=request.data.get('title', doc.title),
                file=file_obj,
                document_type=request.data.get('document_type', doc.document_type),
                application_id=(
                    request.data.get('application')
                    if request.data.get('application') not in (None, '', 'null')
                    else doc.application_id
                ),
                root_document=root,
                version_number=max_version + 1,
                is_current=True,
                is_locked=False,
            )

        serializer = self.get_serializer(new_doc)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
