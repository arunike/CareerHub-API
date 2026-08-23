
from django.db.models import Q
from django.urls import reverse
from rest_framework import serializers

from ..models import Application, Document
from ..services import document_filename


class DocumentSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField(read_only=True)
    file_name = serializers.SerializerMethodField(read_only=True)
    application_details = serializers.SerializerMethodField(read_only=True)
    version_count = serializers.SerializerMethodField(read_only=True)
    root_document_id = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Document
        fields = [
            'id',
            'title',
            'file',
            'file_name',
            'document_type',
            'application',
            'application_details',
            'root_document',
            'root_document_id',
            'version_number',
            'version_count',
            'is_current',
            'is_locked',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'root_document',
            'root_document_id',
            'version_number',
            'version_count',
            'is_current',
            'created_at',
            'updated_at',
        ]

    def get_application_details(self, obj):
        if not obj.application:
            return None
        return {
            'id': obj.application.id,
            'role': obj.application.role_title,
            'company': obj.application.company.name,
        }

    def get_root_document_id(self, obj):
        return obj.root_document_id or obj.id

    def get_file(self, obj):
        if not obj.file:
            return None
        request = self.context.get('request')
        relative_url = reverse('document-download', kwargs={'pk': obj.pk})
        return request.build_absolute_uri(relative_url) if request else relative_url

    def get_file_name(self, obj):
        return document_filename(obj.file)

    def get_version_count(self, obj):
        root_id = obj.root_document_id or obj.id
        return Document.objects.filter(
            (Q(id=root_id) | Q(root_document_id=root_id)) & Q(user=obj.user)
        ).count()

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['application'].queryset = Application.objects.filter(user=request.user)
        else:
            fields['application'].queryset = Application.objects.none()
        return fields


class DocumentExportSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField(read_only=True)
    file_name = serializers.SerializerMethodField(read_only=True)
    application_role = serializers.CharField(source='application.role_title', read_only=True)
    application_company = serializers.CharField(source='application.company.name', read_only=True)

    class Meta:
        model = Document
        fields = [
            'id',
            'title',
            'document_type',
            'file',
            'file_name',
            'application_role',
            'application_company',
            'version_number',
            'is_current',
            'is_locked',
            'created_at',
            'updated_at',
        ]

    def get_file(self, obj):
        if not obj.file:
            return None
        request = self.context.get('request')
        relative_url = reverse('document-download', kwargs={'pk': obj.pk})
        return request.build_absolute_uri(relative_url) if request else relative_url

    def get_file_name(self, obj):
        return document_filename(obj.file)


class TimelineDocumentSerializer(serializers.ModelSerializer):
    file_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Document
        fields = ['id', 'title', 'document_type', 'file_name', 'application']

    def get_file_name(self, obj):
        return document_filename(obj.file)
