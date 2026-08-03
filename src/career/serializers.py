import base64

from django.db.models import Q
from django.urls import reverse
from rest_framework import serializers

from .models import (
    AIArtifact,
    AIArtifactGenerationJob,
    Company,
    Application,
    ApplicationContact,
    InterviewDebrief,
    ApplicationTimelineEntry,
    GoogleSheetSyncConfig,
    GoogleSheetSyncRun,
    Offer,
    OfferDecisionSnapshot,
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

class InterviewDebriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = InterviewDebrief
        fields = [
            'id', 'application', 'stage', 'interview_date', 'questions_asked',
            'went_well', 'weak_areas', 'interviewer_notes', 'confidence',
            'next_steps', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_application(self, value):
        request = self.context.get('request')
        if request and value.user_id != request.user.id:
            raise serializers.ValidationError('Application not found.')
        return value

    def validate_confidence(self, value):
        # No DB CHECK on this column, so the range is enforced here.
        if value is not None and not (1 <= value <= 5):
            raise serializers.ValidationError('Must be between 1 and 5.')
        return value

    def validate(self, attrs):
        application = attrs.get('application', getattr(self.instance, 'application', None))
        stage = attrs.get('stage', getattr(self.instance, 'stage', None))
        if application and stage:
            clash = InterviewDebrief.objects.filter(application=application, stage=stage)
            if self.instance:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {'stage': 'A debrief already exists for this round.'}
                )
        return attrs


class ApplicationContactSerializer(serializers.ModelSerializer):
    # Set when a contact is surfaced on an experience but actually belongs to the
    # application that produced it, so the UI can mark it as inherited.
    inherited = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ApplicationContact
        fields = [
            'id', 'application', 'experience', 'name', 'email', 'notes',
            'is_locked', 'inherited', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_inherited(self, obj):
        return bool(getattr(obj, '_inherited', False))

    def validate_application(self, value):
        # A contact must hang off an application the requester actually owns.
        request = self.context.get('request')
        if value is not None and request and value.user_id != request.user.id:
            raise serializers.ValidationError('Application not found.')
        return value

    def validate_experience(self, value):
        request = self.context.get('request')
        if value is not None and request and value.user_id != request.user.id:
            raise serializers.ValidationError('Experience not found.')
        return value

    def validate_name(self, value):
        cleaned = (value or '').strip()
        if not cleaned:
            raise serializers.ValidationError('Name is required.')
        return cleaned

    def validate(self, attrs):
        # Mirrors the DB check constraint: a contact with neither owner would be
        # unreachable from any screen.
        application = attrs.get('application', getattr(self.instance, 'application', None))
        experience = attrs.get('experience', getattr(self.instance, 'experience', None))
        if not application and not experience:
            raise serializers.ValidationError(
                'A contact must belong to an application or an experience.'
            )
        return attrs


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ['id', 'name', 'website', 'industry', 'created_at', 'updated_at']


class AIArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIArtifact
        fields = [
            'id',
            'artifact_type',
            'client_id',
            'title',
            'summary',
            'payload',
            'source_application',
            'source_offer',
            'source_experience',
            'is_locked',
            'saved_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['source_application'].queryset = Application.objects.filter(user=request.user)
            fields['source_offer'].queryset = Offer.objects.filter(application__user=request.user)
            fields['source_experience'].queryset = Experience.objects.filter(user=request.user)
        else:
            fields['source_application'].queryset = Application.objects.none()
            fields['source_offer'].queryset = Offer.objects.none()
            fields['source_experience'].queryset = Experience.objects.none()
        return fields

    def validate_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Artifact payload must be an object.')
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        artifact, _ = AIArtifact.objects.update_or_create(
            user=request.user,
            client_id=validated_data['client_id'],
            defaults=validated_data,
        )
        return artifact


class AIArtifactGenerationJobSerializer(serializers.ModelSerializer):
    artifact_client_id = serializers.CharField(source='artifact.client_id', read_only=True)

    class Meta:
        model = AIArtifactGenerationJob
        fields = [
            'id',
            'kind',
            'status',
            'input_payload',
            'result_payload',
            'error_message',
            'artifact',
            'artifact_client_id',
            'started_at',
            'completed_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'status',
            'result_payload',
            'error_message',
            'artifact',
            'artifact_client_id',
            'started_at',
            'completed_at',
            'created_at',
            'updated_at',
        ]

    def validate_input_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Job input payload must be an object.')
        messages = value.get('messages')
        if not isinstance(messages, list) or not messages:
            raise serializers.ValidationError('Job input payload must include messages.')
        artifact = value.get('artifact')
        if not isinstance(artifact, dict):
            raise serializers.ValidationError('Job input payload must include artifact metadata.')
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        return AIArtifactGenerationJob.objects.create(user=request.user, **validated_data)


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

    def validate_refresh_starts_year(self, value):
        # The DB column carries no CHECK constraint (see Offer.refresh_starts_year),
        # so the four-year projection window is enforced here.
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


# Stages that mean no interview has happened yet. Anything else — a numbered round,
# onsite, offer, accepted — means the process got past screening.
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
            'commute_cost_value', 'commute_cost_frequency',
            'free_food_perk_value', 'free_food_perk_frequency',
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


class GoogleSheetSyncConfigSerializer(serializers.ModelSerializer):
    share_with_email = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = GoogleSheetSyncConfig
        fields = [
            'id',
            'name',
            'sheet_url',
            'spreadsheet_id',
            'worksheet_name',
            'gid',
            'target_type',
            'column_mapping',
            'overwrite_strategies',
            'enabled',
            'sync_time',
            'sync_timezone',
            'header_row',
            'missing_row_strategy',
            'missing_row_delete_after_days',
            'last_synced_at',
            'last_status',
            'last_error',
            'last_result',
            'share_with_email',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'spreadsheet_id',
            'gid',
            'last_synced_at',
            'last_status',
            'last_error',
            'last_result',
            'share_with_email',
            'created_at',
            'updated_at',
        ]

    def get_share_with_email(self, obj):
        from .services.google_sheets import get_service_account_email

        return get_service_account_email()

    def validate_header_row(self, value):
        if value < 1:
            raise serializers.ValidationError('Header row must be 1 or greater.')
        return value

    def validate_sync_timezone(self, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        value = (value or '').strip() or 'America/Los_Angeles'
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError('Enter a valid IANA timezone, such as America/Los_Angeles.') from exc
        return value

    def validate_column_mapping(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Column mapping must be an object.')
        cleaned = {}
        for key, label in value.items():
            if not isinstance(key, str) or not isinstance(label, str):
                raise serializers.ValidationError('Column mapping keys and values must be text.')
            if key.strip() and label.strip():
                cleaned[key.strip()] = label.strip()
        return cleaned

    def validate(self, attrs):
        from .services.google_sheets import parse_google_sheet_url

        sheet_url = attrs.get('sheet_url') or getattr(self.instance, 'sheet_url', '')
        spreadsheet_id, gid = parse_google_sheet_url(sheet_url)
        if not spreadsheet_id:
            raise serializers.ValidationError({'sheet_url': 'Enter a valid Google Sheets link.'})
        attrs['spreadsheet_id'] = spreadsheet_id
        if gid:
            attrs['gid'] = gid
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        return GoogleSheetSyncConfig.objects.create(user=request.user, **validated_data)


class GoogleSheetSyncRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoogleSheetSyncRun
        fields = [
            'id',
            'config',
            'status',
            'started_at',
            'completed_at',
            'summary',
            'changes',
            'error_details',
        ]
        read_only_fields = fields

class ApplicationExportSerializer(serializers.ModelSerializer):
    company = serializers.CharField(source='company.name', read_only=True)
    
    class Meta:
        model = Application
        fields = [
            'id', 'company', 'role_title', 'status', 'rto_policy', 'rto_days_per_week',
            'commute_cost_value', 'commute_cost_frequency',
            'free_food_perk_value', 'free_food_perk_frequency',
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


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ['id', 'title', 'description', 'status', 'priority', 'due_date', 'position', 'created_at', 'updated_at']

class ExperienceSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField(read_only=True)
    level = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = Experience
        fields = ['id', 'title', 'company', 'level', 'work_email', 'location', 'start_date', 'end_date', 'is_current', 'description', 'skills', 'logo', 'employment_type', 'is_promotion', 'is_return_offer', 'is_locked', 'is_pinned', 'position', 'offer', 'hourly_rate', 'hours_per_day', 'working_days_per_week', 'total_hours_worked', 'overtime_hours', 'overtime_rate', 'overtime_multiplier', 'total_earnings_override', 'base_salary', 'bonus', 'equity', 'team_history', 'schedule_phases', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

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
