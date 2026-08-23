
from rest_framework import serializers

from ..models import Offer, Experience
from ..services import normalize_logo_url
from ..skills_extractor import extract_skills_from_text


class ExperienceSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField(read_only=True)
    level = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = Experience
        fields = ['id', 'title', 'company', 'level', 'work_email', 'location', 'start_date', 'end_date', 'is_current', 'description', 'skills', 'logo', 'employment_type', 'is_promotion', 'is_return_offer', 'is_locked', 'is_pinned', 'position', 'offer', 'career_record', 'hourly_rate', 'hours_per_day', 'working_days_per_week', 'total_hours_worked', 'overtime_hours', 'overtime_rate', 'overtime_multiplier', 'total_earnings_override', 'base_salary', 'bonus', 'equity', 'team_history', 'schedule_phases', 'created_at', 'updated_at']
        read_only_fields = ['id', 'career_record', 'created_at', 'updated_at']

    def get_logo(self, obj):
        return normalize_logo_url(obj.logo)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        try:
            data['level'] = getattr(instance, 'level', '') or ''
        except Exception:
            data['level'] = ''
        try:
            data['position'] = getattr(instance, 'position', None)
        except Exception:
            data['position'] = None
        return data

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
