import base64

from django.db.models import Q
from django.urls import reverse
from rest_framework import serializers

from .models import (
    Company,
    Application,
    Offer,
    Document,
    Task,
    Experience
)
from .services import (
    document_filename,
    logo_content_type,
    logo_filename,
    normalize_logo_url,
    read_logo_bytes,
)
from .skills_extractor import extract_skills_from_text

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ['id', 'name', 'website', 'industry', 'created_at', 'updated_at']

class OfferSerializer(serializers.ModelSerializer):
    application_details = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Offer
        fields = '__all__'

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['application'].queryset = Application.objects.filter(user=request.user)
        else:
            fields['application'].queryset = Application.objects.none()
        return fields

    def get_application_details(self, obj):
        return {
            'company': obj.application.company.name,
            'role_title': obj.application.role_title,
        }

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

class ApplicationSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(write_only=True)
    company_details = serializers.SerializerMethodField(read_only=True)
    offer = OfferSerializer(read_only=True)
    
    class Meta:
        model = Application
        fields = [
            'id', 'company_name', 'company_details', 'role_title', 'status', 'employment_type', 'job_link',
            'rto_policy', 'rto_days_per_week',
            'commute_cost_value', 'commute_cost_frequency',
            'free_food_perk_value', 'free_food_perk_frequency',
            'tax_base_rate', 'tax_bonus_rate', 'tax_equity_rate', 'monthly_rent_override',
            'salary_range', 'location', 'office_location', 'notes', 'current_round', 'is_locked',
            'date_applied', 'offer', 'created_at'
        ]
        extra_kwargs = {
            'company': {'required': False}
        }

    def get_company_details(self, obj):
        return CompanySerializer(obj.company).data

    def create(self, validated_data):
        company_name = validated_data.pop('company_name')
        request = self.context.get('request')
        company, _ = Company.objects.get_or_create(user=request.user, name=company_name)
        application = Application.objects.create(user=request.user, company=company, **validated_data)
        return application

    def update(self, instance, validated_data):
        if 'company_name' in validated_data:
            company_name = validated_data.pop('company_name')
            request = self.context.get('request')
            company, _ = Company.objects.get_or_create(user=request.user, name=company_name)
            instance.company = company
        
        return super().update(instance, validated_data)

class ApplicationExportSerializer(serializers.ModelSerializer):
    company = serializers.CharField(source='company.name', read_only=True)
    
    class Meta:
        model = Application
        fields = [
            'id', 'company', 'role_title', 'status', 'rto_policy', 'rto_days_per_week',
            'commute_cost_value', 'commute_cost_frequency',
            'free_food_perk_value', 'free_food_perk_frequency',
            'tax_base_rate', 'tax_bonus_rate', 'tax_equity_rate', 'monthly_rent_override',
            'current_round', 'job_link', 'salary_range', 'location', 'office_location', 'notes',
            'date_applied', 'created_at', 'updated_at'
        ]


class OfferExportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offer
        exclude = ['application']


class ApplicationImportExportSerializer(serializers.ModelSerializer):
    company = serializers.CharField(source='company.name', read_only=True)

    class Meta:
        model = Application
        fields = [
            'id',
            'company',
            'role_title',
            'status',
            'job_link',
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
            'salary_range',
            'location',
            'office_location',
            'employment_type',
            'notes',
            'current_round',
            'is_locked',
            'date_applied',
            'created_at',
            'updated_at',
        ]


class ExperienceExportSerializer(serializers.ModelSerializer):
    offer_reference_id = serializers.SerializerMethodField()
    offer_data = serializers.SerializerMethodField()
    offer_application_data = serializers.SerializerMethodField()
    logo_filename = serializers.SerializerMethodField()
    logo_content_type = serializers.SerializerMethodField()
    logo_base64 = serializers.SerializerMethodField()

    class Meta:
        model = Experience
        fields = [
            'id',
            'title',
            'company',
            'location',
            'start_date',
            'end_date',
            'is_current',
            'description',
            'skills',
            'employment_type',
            'is_promotion',
            'is_return_offer',
            'is_locked',
            'is_pinned',
            'hourly_rate',
            'hours_per_day',
            'working_days_per_week',
            'total_hours_worked',
            'overtime_hours',
            'overtime_rate',
            'overtime_multiplier',
            'total_earnings_override',
            'base_salary',
            'bonus',
            'equity',
            'team_history',
            'schedule_phases',
            'offer_reference_id',
            'offer_data',
            'offer_application_data',
            'logo_filename',
            'logo_content_type',
            'logo_base64',
            'created_at',
            'updated_at',
        ]

    def get_offer_reference_id(self, obj):
        return obj.offer_id

    def get_offer_data(self, obj):
        if not obj.offer:
            return None
        return OfferExportSerializer(obj.offer).data

    def get_offer_application_data(self, obj):
        if not obj.offer or not obj.offer.application:
            return None
        return ApplicationImportExportSerializer(obj.offer.application).data

    def get_logo_filename(self, obj):
        return logo_filename(obj.logo)

    def get_logo_content_type(self, obj):
        return logo_content_type(obj.logo)

    def get_logo_base64(self, obj):
        content = read_logo_bytes(obj.logo)
        if content is None:
            return None
        try:
            return base64.b64encode(content).decode('ascii')
        except Exception:
            return None


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ['id', 'title', 'description', 'status', 'priority', 'due_date', 'position', 'created_at', 'updated_at']

class ExperienceSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Experience
        fields = ['id', 'title', 'company', 'location', 'start_date', 'end_date', 'is_current', 'description', 'skills', 'logo', 'employment_type', 'is_promotion', 'is_return_offer', 'is_locked', 'is_pinned', 'offer', 'hourly_rate', 'hours_per_day', 'working_days_per_week', 'total_hours_worked', 'overtime_hours', 'overtime_rate', 'overtime_multiplier', 'total_earnings_override', 'base_salary', 'bonus', 'equity', 'team_history', 'schedule_phases', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_logo(self, obj):
        return normalize_logo_url(obj.logo)

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['offer'].queryset = Offer.objects.filter(application__user=request.user)
        else:
            fields['offer'].queryset = Offer.objects.none()
        return fields

    def create(self, validated_data):
        description = validated_data.get('description', '')
        company = validated_data.get('company', '')
        title = validated_data.get('title', '')
        
        if 'skills' not in validated_data:
            try:
                validated_data['skills'] = extract_skills_from_text(description, company=company, title=title)
            except Exception as e:
                validated_data['skills'] = []

        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            validated_data['user'] = request.user

        return super().create(validated_data)

    def update(self, instance, validated_data):
        description = validated_data.get('description', instance.description)
        company = validated_data.get('company', instance.company)
        title = validated_data.get('title', instance.title)

        if 'skills' in validated_data:
            pass  # Keep manual overrides
        elif 'description' in validated_data and validated_data['description'] != instance.description:
            try:
                validated_data['skills'] = extract_skills_from_text(description, company=company, title=title)
            except Exception:
                validated_data['skills'] = instance.skills or []

        return super().update(instance, validated_data)
