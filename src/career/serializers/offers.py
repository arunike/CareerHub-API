import datetime

from django.db import transaction
from rest_framework import serializers

from ..models import Application, Offer, OfferDecisionJournal, OfferDecisionSnapshot, StockPrice
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


class StockPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockPrice
        fields = ['id', 'symbol', 'price', 'as_of', 'source', 'note', 'updated_at']
        read_only_fields = ['id', 'updated_at']

    def validate_symbol(self, value):
        symbol = (value or '').strip().upper()
        if not symbol:
            raise serializers.ValidationError('A ticker is required.')
        if not symbol.replace('.', '').replace('-', '').isalnum():
            raise serializers.ValidationError('A ticker may only contain letters, numbers, dots and dashes.')
        return symbol

    def validate_price(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError('A price cannot be negative.')
        return value

    def create(self, validated_data):
        # Upsert: re-entering a ticker updates the price rather than failing the unique constraint.
        user = self.context['request'].user
        symbol = validated_data.pop('symbol')
        instance, _ = StockPrice.objects.update_or_create(
            user=user, symbol=symbol, defaults=validated_data
        )
        return instance


class OfferDecisionJournalSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField(read_only=True)
    role_title = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = OfferDecisionJournal
        fields = [
            'id', 'offer', 'company_name', 'role_title', 'decision', 'decided_on', 'started_on',
            'reasons', 'concerns', 'reviews', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'company_name', 'role_title', 'created_at', 'updated_at']

    def get_company_name(self, obj):
        company = getattr(obj.offer.application, 'company', None)
        return getattr(company, 'name', '') or obj.offer.application.custom_company_name or ''

    def get_role_title(self, obj):
        return obj.offer.application.role_title or ''

    def validate_reviews(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Reviews must be a list.')
        for entry in value:
            if not isinstance(entry, dict):
                raise serializers.ValidationError('Each review must be an object.')
            if not isinstance(entry.get('milestone'), int):
                raise serializers.ValidationError('Each review needs a milestone in days.')
        return value

    def validate_offer(self, value):
        # The journal is one per decision, and an offer belongs to exactly one user.
        request = self.context.get('request')
        if request and value.application.user_id != request.user.id:
            raise serializers.ValidationError('That offer does not belong to you.')
        return value
