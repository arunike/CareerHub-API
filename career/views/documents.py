from io import BytesIO

from django.db import transaction
from django.db.models import Max, Q
from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from availability.utils import export_data

from ..models import Application, Document
from ..serializers import DocumentExportSerializer, DocumentSerializer
from ..services import (
    delete_document_asset,
    document_content_type,
    document_filename,
    read_document_bytes,
    store_document_file,
)
from ..upload_validation import validate_document_upload


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _base_queryset(self):
        return Document.objects.filter(user=self.request.user).order_by('-updated_at')

    def get_queryset(self):
        queryset = self._base_queryset()
        include_versions = self.request.query_params.get('include_versions')
        if include_versions in ('1', 'true', 'True'):
            return queryset
        return queryset.filter(is_current=True)

    def _version_queryset(self, doc):
        root = doc.root_document or doc
        return self._base_queryset().filter(Q(id=root.id) | Q(root_document_id=root.id))

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        version_queryset = self._version_queryset(instance)
        if version_queryset.filter(is_locked=True).exists():
            return Response(
                {
                    'error': (
                        'This document has locked versions and cannot be deleted. '
                        'Unlock every version first.'
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        version_queryset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)
        validate_document_upload(file_obj)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        stored_file = None
        try:
            with transaction.atomic():
                document = Document.objects.create(
                    user=request.user,
                    title=validated['title'],
                    file=None,
                    document_type=validated.get('document_type', 'RESUME'),
                    application=validated.get('application'),
                    root_document=None,
                    version_number=1,
                    is_current=True,
                    is_locked=False,
                )
                stored_file = store_document_file(
                    file_obj,
                    user_id=request.user.id,
                    root_document_id=document.id,
                    document_id=document.id,
                    version_number=document.version_number,
                )
                document.file = stored_file
                document.save(update_fields=['file'])
        except Exception:
            if stored_file:
                delete_document_asset(stored_file)
            raise

        output = self.get_serializer(document)
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        root_ids = {
            doc.root_document_id or doc.id
            for doc in self.get_queryset().only('id', 'root_document_id')
        }
        deleted_count = 0
        preserved_count = 0

        for root_id in root_ids:
            version_queryset = self._base_queryset().filter(
                Q(id=root_id) | Q(root_document_id=root_id)
            )
            if version_queryset.filter(is_locked=True).exists():
                preserved_count += version_queryset.count()
                continue
            count, _ = version_queryset.delete()
            deleted_count += count

        return Response(
            {
                'message': (
                    f'Deleted {deleted_count} document records. '
                    f'Preserved {preserved_count} locked version records.'
                )
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), DocumentExportSerializer, fmt, 'documents')

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        doc = self.get_object()
        versions = self._version_queryset(doc).order_by('-version_number')
        serializer = self.get_serializer(versions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        doc = self.get_object()
        content = read_document_bytes(doc.file)
        if content is None:
            return Response({'error': 'Document file was not found.'}, status=status.HTTP_404_NOT_FOUND)

        filename = document_filename(doc.file) or f"{doc.title}.bin"
        response = FileResponse(
            BytesIO(content),
            content_type=document_content_type(doc.file) or 'application/octet-stream',
            filename=filename,
        )
        response['Content-Length'] = str(len(content))
        return response

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def add_version(self, request, pk=None):
        doc = self.get_object()
        root = doc.root_document or doc
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)
        validate_document_upload(file_obj)

        requested_application_id = request.data.get('application')
        if requested_application_id in (None, '', 'null'):
            application_id = doc.application_id
        else:
            if not Application.objects.filter(id=requested_application_id, user=request.user).exists():
                return Response(
                    {'error': 'Selected application was not found for this account.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            application_id = requested_application_id

        stored_file = None
        try:
            with transaction.atomic():
                current_versions = self._version_queryset(root)
                max_version = current_versions.aggregate(max_v=Max('version_number'))['max_v'] or 1
                current_versions.update(is_current=False)

                new_doc = Document.objects.create(
                    user=request.user,
                    title=request.data.get('title', doc.title),
                    file=None,
                    document_type=request.data.get('document_type', doc.document_type),
                    application_id=application_id,
                    root_document=root,
                    version_number=max_version + 1,
                    is_current=True,
                    is_locked=False,
                )
                stored_file = store_document_file(
                    file_obj,
                    user_id=request.user.id,
                    root_document_id=root.id,
                    document_id=new_doc.id,
                    version_number=new_doc.version_number,
                )
                new_doc.file = stored_file
                new_doc.save(update_fields=['file'])
        except Exception:
            if stored_file:
                delete_document_asset(stored_file)
            raise

        serializer = self.get_serializer(new_doc)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
