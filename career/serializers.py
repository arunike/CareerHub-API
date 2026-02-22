from rest_framework import serializers
from .models import Company, Application, Offer, Document

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

    class Meta:
        model = Document
        fields = ['id', 'title', 'file', 'document_type', 'application', 'application_details', 'created_at', 'updated_at']

    def get_application_details(self, obj):
        if not obj.application:
            return None
        return {
            'id': obj.application.id,
            'role': obj.application.role_title,
            'company': obj.application.company.name,
        }

class DocumentExportSerializer(serializers.ModelSerializer):
    application_role = serializers.CharField(source='application.role_title', read_only=True)
    application_company = serializers.CharField(source='application.company.name', read_only=True)

    class Meta:
        model = Document
        fields = ['id', 'title', 'document_type', 'file', 'application_role', 'application_company', 'created_at', 'updated_at']

class ApplicationSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(write_only=True)
    company_details = serializers.SerializerMethodField(read_only=True)
    offer = OfferSerializer(read_only=True)
    
    class Meta:
        model = Application
        fields = ['id', 'company_name', 'company_details', 'role_title', 'status', 'job_link', 'rto_policy', 'salary_range', 'location', 'notes', 'current_round', 'is_locked', 'date_applied', 'offer', 'created_at']
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
        fields = ['id', 'company', 'role_title', 'status', 'rto_policy', 'current_round', 'job_link', 'salary_range', 'location', 'notes', 'date_applied', 'created_at', 'updated_at']
