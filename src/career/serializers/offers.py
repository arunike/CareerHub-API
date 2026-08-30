import datetime

from django.db import transaction
from rest_framework import serializers

from ..models import Application, Offer, OfferDecisionSnapshot
from ..services.offers import sync_application_status_for_offer_decision


class OfferSerializer(serializers.ModelSerializer):
    application_details = serializers.SerializerMethodField(read_only=True)
    linked_experience = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Offer
        fields = '__all__'

    def get_linked_experience(self, obj):
        # start_date is nullable on a hand-created row, so it is coerced for ordering only.
        experience = max(
            obj.experiences.all(),
            key=lambda e: (e.start_date is not None, e.start_date or datetime.date.min),
            default=None,
        )
        if experience is None:
            return None
        return {
            'id': experience.id,
            'title': experience.title,
            'company': experience.company,
            'start_date': experience.start_date,
            'end_date': experience.end_date,
            'is_current': experience.is_current,
        }

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['application'].queryset = Application.objects.filter(user=request.user)
        else:
            fields['application'].queryset = Application.objects.none()
        return fields

    def validate_refresh_starts_year(self, value):
        # No CHECK constraint on the column, so the four-year window is enforced here.
        if value is None:
            return value
        if value < 1 or value > 4:
            raise serializers.ValidationError('Must be between 1 and 4.')
        return value

    def validate_annual_refresh_value(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError('Cannot be negative.')
        return value

    def validate(self, attrs):
        application = attrs.get('application')
        if application and not self.instance:
            if hasattr(application, 'offer'):
                raise serializers.ValidationError({
                    'application': 'An offer already exists for this application.'
                })
        return attrs

    def update(self, instance, validated_data):
        previous_decision_status = instance.final_decision_status
        decision_status_changed = 'final_decision_status' in validated_data

        with transaction.atomic():
            offer = super().update(instance, validated_data)
            if decision_status_changed:
                sync_application_status_for_offer_decision(offer, previous_decision_status)
        return offer

    def get_application_details(self, obj):
        try:
            app = getattr(obj, 'application', None)
            if not app:
                return {'company': '', 'role_title': '', 'level': '', 'location': '', 'employment_type': 'full_time'}
            company_name = app.company.name if (hasattr(app, 'company') and app.company) else ''
            role_title = getattr(app, 'role_title', '') or ''
            try:
                level = getattr(app, 'level', '') or ''
            except Exception:
                level = ''
            try:
                location = getattr(app, 'office_location', '') or getattr(app, 'location', '') or ''
            except Exception:
                location = ''
            try:
                emp_type = getattr(app, 'employment_type', 'full_time') or 'full_time'
            except Exception:
                emp_type = 'full_time'
            return {
                'company': company_name,
                'role_title': role_title,
                'level': level,
                'location': location,
                'employment_type': emp_type,
            }
        except Exception:
            return {'company': '', 'role_title': '', 'level': '', 'location': '', 'employment_type': 'full_time'}


class OfferDecisionSnapshotSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='offer.application.company.name', read_only=True)
    role_title = serializers.CharField(source='offer.application.role_title', read_only=True)

    class Meta:
        model = OfferDecisionSnapshot
        fields = [
            'id',
            'offer',
            'company_name',
            'role_title',
            'title',
            'notes',
            'decision_score',
            'rank',
            'total_comp',
            'adjusted_value',
            'monthly_rent',
            'commute_cost_annual',
            'tax_snapshot',
            'score_categories',
            'offer_snapshot',
            'adjustment_snapshot',
            'is_locked',
            'captured_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'company_name', 'role_title', 'captured_at', 'updated_at']

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['offer'].queryset = Offer.objects.filter(application__user=request.user)
        else:
            fields['offer'].queryset = Offer.objects.none()
        return fields

    def validate_score_categories(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Score categories must be a list.')
        return value

    def validate_tax_snapshot(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Tax snapshot must be an object.')
        return value

    def validate_offer_snapshot(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Offer snapshot must be an object.')
        return value

    def validate_adjustment_snapshot(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Adjustment snapshot must be an object.')
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        return OfferDecisionSnapshot.objects.create(user=request.user, **validated_data)
