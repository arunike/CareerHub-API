import base64

from rest_framework import serializers

from ..models import Application, Offer, Experience
from ..services import logo_content_type, logo_filename, read_logo_bytes


class ApplicationExportSerializer(serializers.ModelSerializer):
    company = serializers.CharField(source='company.name', read_only=True)
    
    class Meta:
        model = Application
        fields = [
            'id', 'company', 'role_title', 'status', 'rto_policy', 'rto_days_per_week',
            'commute_cost_value', 'commute_cost_frequency', 'commute_options',
            'free_food_perk_value', 'free_food_perk_frequency',
            'free_food_meals', 'free_food_value_per_meal',
            'tax_base_rate', 'tax_bonus_rate', 'tax_equity_rate', 'monthly_rent_override',
            'current_round', 'job_link', 'salary_range', 'location', 'office_location',
            'source_removed_at', 'source_removed_delete_after',
            'visa_sponsorship', 'day_one_gc', 'flexible_hours_policy', 'travel_frequency', 'growth_score', 'work_life_score', 'brand_score', 'team_score',
            'notes',
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
            'visa_sponsorship',
            'day_one_gc',
            'flexible_hours_policy',
            'travel_frequency',
            'growth_score',
            'work_life_score',
            'brand_score',
            'team_score',
            'employment_type',
            'notes',
            'current_round',
            'source_removed_at',
            'source_removed_delete_after',
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
