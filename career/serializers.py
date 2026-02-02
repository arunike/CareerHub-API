from rest_framework import serializers
from .models import Company, Application, Offer

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'

class OfferSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offer
        fields = '__all__'

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
