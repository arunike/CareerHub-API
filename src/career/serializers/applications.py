
from django.db.models import Q
from rest_framework import serializers

from ..models import Company, Application, ApplicationTimelineEntry, Document, Task
from .documents import TimelineDocumentSerializer
from .offers import OfferSerializer


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ['id', 'name', 'website', 'industry', 'created_at', 'updated_at']


class ApplicationTimelineEntrySerializer(serializers.ModelSerializer):
    stage_label = serializers.SerializerMethodField(read_only=True)
    document_details = TimelineDocumentSerializer(source='documents', many=True, read_only=True)

    class Meta:
        model = ApplicationTimelineEntry
        fields = [
            'id',
            'application',
            'stage',
            'stage_label',
            'stage_order',
            'display_title',
            'event_date',
            'notes',
            'documents',
            'document_details',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['stage_label', 'stage_order', 'document_details', 'created_at', 'updated_at']

    def get_stage_label(self, obj):
        return obj.display_title or obj.stage

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['application'].queryset = Application.objects.filter(user=request.user)
            document_queryset = Document.objects.filter(user=request.user, is_current=True)
        else:
            fields['application'].queryset = Application.objects.none()
            document_queryset = Document.objects.none()

        documents_field = fields['documents']
        if hasattr(documents_field, 'child_relation'):
            documents_field.child_relation.queryset = document_queryset
        else:
            documents_field.queryset = document_queryset
        return fields

    def validate(self, attrs):
        request = self.context.get('request')
        application = attrs.get('application') or getattr(self.instance, 'application', None)
        if application and request and application.user_id != request.user.id:
            raise serializers.ValidationError({'application': 'Selected application was not found for this account.'})
        if self.instance:
            if 'stage' in attrs and attrs['stage'] != self.instance.stage:
                raise serializers.ValidationError({'stage': 'The synced stage key cannot be changed.'})
            if 'application' in attrs and attrs['application'] != self.instance.application:
                raise serializers.ValidationError({'application': 'A timeline entry cannot be moved to another application.'})
        return attrs

    def create(self, validated_data):
        provided_fields = set(validated_data)
        documents = validated_data.pop('documents', None)
        existing = ApplicationTimelineEntry.objects.filter(
            user=validated_data['user'],
            application=validated_data['application'],
            stage=validated_data['stage'],
        ).filter(
            Q(deleted_by_user_at__isnull=False) | Q(hidden_by_sync_at__isnull=False)
        ).first()

        if existing:
            for field, value in validated_data.items():
                if field != 'user':
                    setattr(existing, field, value)
            existing.deleted_by_user_at = None
            existing.hidden_by_sync_at = None
            if 'event_date' in provided_fields:
                existing.event_date_is_user_override = True
            if 'notes' in provided_fields:
                existing.notes_is_user_override = True
            existing.save()
            if documents is not None:
                existing.documents.set(documents)
            return existing

        validated_data['event_date_is_user_override'] = 'event_date' in provided_fields
        validated_data['notes_is_user_override'] = 'notes' in provided_fields
        if documents is not None:
            validated_data['documents'] = documents
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'event_date' in validated_data and validated_data['event_date'] != instance.event_date:
            validated_data['event_date_is_user_override'] = True
        if 'notes' in validated_data and validated_data['notes'] != instance.notes:
            validated_data['notes_is_user_override'] = True
        return super().update(instance, validated_data)


# No interview yet; anything else means the process got past screening.


NON_INTERVIEW_STAGES = {'APPLIED', 'REJECTED', 'GHOSTED', 'REMOVED_FROM_SHEET'}


class ApplicationSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(write_only=True)
    has_reached_interview = serializers.SerializerMethodField(read_only=True)
    company_details = serializers.SerializerMethodField(read_only=True)
    offer = OfferSerializer(read_only=True)
    
    class Meta:
        model = Application
        fields = [
            'id', 'company_name', 'company_details', 'role_title', 'status', 'employment_type', 'level', 'job_link',
            'rto_policy', 'rto_days_per_week',
            'commute_cost_value', 'commute_cost_frequency', 'commute_options',
            'free_food_perk_value', 'free_food_perk_frequency',
            'free_food_meals', 'free_food_value_per_meal',
            'tax_base_rate', 'tax_bonus_rate', 'tax_equity_rate', 'monthly_rent_override',
            'salary_range', 'location', 'office_location',
            'visa_sponsorship', 'day_one_gc', 'flexible_hours_policy', 'travel_frequency', 'growth_score', 'work_life_score', 'brand_score', 'team_score',
            'job_description', 'submitted_documents', 'notes', 'current_round', 'is_locked',
            'has_reached_interview',
            'source_removed_at', 'source_removed_delete_after',
            'date_applied', 'offer', 'created_at'
        ]
        extra_kwargs = {
            'company': {'required': False}
        }

    def get_has_reached_interview(self, obj):
        # The list view annotates this; fall back to a query for single objects.
        annotated = getattr(obj, 'reached_interview_annotation', None)
        if annotated is not None:
            return bool(annotated)
        if obj.status not in NON_INTERVIEW_STAGES:
            return True
        return obj.timeline_entries.exclude(stage__in=NON_INTERVIEW_STAGES).exists()

    def get_company_details(self, obj):
        return CompanySerializer(obj.company).data

    def validate_status(self, value):
        if value == 'ACCEPTED' and not (
            self.instance and self.instance.status == 'ACCEPTED'
        ):
            raise serializers.ValidationError('Accept the offer from the Offers page.')
        return value

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


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ['id', 'title', 'description', 'status', 'priority', 'due_date', 'position', 'created_at', 'updated_at']
