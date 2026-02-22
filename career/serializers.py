from rest_framework import serializers
from django.db.models import Q
from .models import Company, Application, Offer, Document, Task

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'

class OfferSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offer
        fields = '__all__'

class DocumentSerializer(serializers.ModelSerializer):
    application_details = serializers.SerializerMethodField(read_only=True)
    version_count = serializers.SerializerMethodField(read_only=True)
    root_document_id = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Document
        fields = [
            'id',
            'title',
            'file',
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

    def get_version_count(self, obj):
        root_id = obj.root_document_id or obj.id
        return Document.objects.filter(
            Q(id=root_id) | Q(root_document_id=root_id)
        ).count()

class DocumentExportSerializer(serializers.ModelSerializer):
    application_role = serializers.CharField(source='application.role_title', read_only=True)
    application_company = serializers.CharField(source='application.company.name', read_only=True)

    class Meta:
        model = Document
        fields = [
            'id',
            'title',
            'document_type',
            'file',
            'application_role',
            'application_company',
            'version_number',
            'is_current',
            'is_locked',
            'created_at',
            'updated_at',
        ]

class ApplicationSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(write_only=True)
    company_details = serializers.SerializerMethodField(read_only=True)
    offer = OfferSerializer(read_only=True)
    
    class Meta:
        model = Application
        fields = [
            'id', 'company_name', 'company_details', 'role_title', 'status', 'job_link',
            'rto_policy', 'rto_days_per_week',
            'commute_cost_value', 'commute_cost_frequency',
            'free_food_perk_value', 'free_food_perk_frequency',
            'tax_base_rate', 'tax_bonus_rate', 'tax_equity_rate', 'monthly_rent_override',
            'salary_range', 'location', 'notes', 'current_round', 'is_locked',
            'date_applied', 'offer', 'created_at'
        ]
        extra_kwargs = {
            'company': {'required': False}
        }

    def get_company_details(self, obj):
        return CompanySerializer(obj.company).data

    def create(self, validated_data):
        company_name = validated_data.pop('company_name')
        company, _ = Company.objects.get_or_create(name=company_name)
        application = Application.objects.create(company=company, **validated_data)
        return application

    def update(self, instance, validated_data):
        if 'company_name' in validated_data:
            company_name = validated_data.pop('company_name')
            company, _ = Company.objects.get_or_create(name=company_name)
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
            'current_round', 'job_link', 'salary_range', 'location', 'notes',
            'date_applied', 'created_at', 'updated_at'
        ]


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = '__all__'
