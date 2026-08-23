
from django.db import transaction
from rest_framework import serializers

from ..models import Application, CareerRecord, Contact, ContactContext, ContactRelationship, InterviewDebrief, Experience
from ..services.career_records import (
    ensure_application_career_record,
    ensure_experience_career_record,
)


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


class ContactContextSerializer(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ContactContext
        fields = [
            'id', 'career_record', 'application', 'experience', 'source',
            'summary', 'created_at',
        ]

    def get_summary(self, obj):
        if obj.application_id:
            application = obj.application
            return {
                'type': 'APPLICATION',
                'company': application.company.name,
                'role': application.role_title,
                'status': application.status,
            }
        experience = obj.experience
        return {
            'type': 'EXPERIENCE',
            'company': experience.company,
            'role': experience.title,
            'status': 'CURRENT' if experience.is_current else 'PAST',
        }


class ContactRelationshipSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField(read_only=True)
    source_name = serializers.SerializerMethodField(read_only=True)
    target_name = serializers.CharField(source='target_contact.name', read_only=True)

    class Meta:
        model = ContactRelationship
        fields = [
            'id', 'source_contact', 'source_name', 'target_contact', 'target_name',
            'kind', 'custom_label', 'label', 'career_record', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_label(self, obj):
        return obj.custom_label if obj.kind == 'CUSTOM' else obj.get_kind_display()

    def get_source_name(self, obj):
        return obj.source_contact.name if obj.source_contact_id else 'Me'

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            contacts = Contact.objects.filter(user=user)
            fields['source_contact'].queryset = contacts
            fields['target_contact'].queryset = contacts
            fields['career_record'].queryset = CareerRecord.objects.filter(user=user)
        else:
            fields['source_contact'].queryset = Contact.objects.none()
            fields['target_contact'].queryset = Contact.objects.none()
            fields['career_record'].queryset = CareerRecord.objects.none()
        return fields

    def validate(self, attrs):
        source = attrs.get('source_contact', getattr(self.instance, 'source_contact', None))
        target = attrs.get('target_contact', getattr(self.instance, 'target_contact', None))
        kind = attrs.get('kind', getattr(self.instance, 'kind', 'CONTACT'))
        custom_label = (attrs.get('custom_label', getattr(self.instance, 'custom_label', '')) or '').strip()
        if source and target and source.id == target.id:
            raise serializers.ValidationError('A contact cannot be related to itself.')
        if kind == 'CUSTOM' and not custom_label:
            raise serializers.ValidationError({'custom_label': 'Enter a custom relationship.'})
        if kind != 'CUSTOM':
            custom_label = ''
        attrs['custom_label'] = custom_label

        request = self.context.get('request')
        duplicate = ContactRelationship.objects.filter(
            user=request.user,
            source_contact=source,
            target_contact=target,
            kind=kind,
            custom_label__iexact=custom_label,
        )
        if self.instance:
            duplicate = duplicate.exclude(id=self.instance.id)
        if duplicate.exists():
            raise serializers.ValidationError('This relationship already exists.')
        return attrs

    def create(self, validated_data):
        return ContactRelationship.objects.create(
            user=self.context['request'].user,
            **validated_data,
        )


class ContactSerializer(serializers.ModelSerializer):
    application = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    experience = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    connect_to_self = serializers.BooleanField(write_only=True, required=False)
    relationship_kind = serializers.ChoiceField(
        choices=ContactRelationship.KIND_CHOICES,
        write_only=True,
        required=False,
    )
    custom_label = serializers.CharField(write_only=True, required=False, allow_blank=True)
    contexts = ContactContextSerializer(many=True, read_only=True)
    inherited = serializers.SerializerMethodField(read_only=True)
    possible_duplicate = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Contact
        fields = [
            'id', 'application', 'experience', 'name', 'email', 'job_title', 'company',
            'notes', 'is_locked', 'contexts',
            'connect_to_self', 'relationship_kind', 'custom_label', 'inherited',
            'possible_duplicate', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_name(self, value):
        cleaned = (value or '').strip()
        if not cleaned:
            raise serializers.ValidationError('Name is required.')
        return cleaned

    def validate_email(self, value):
        return (value or '').strip().lower()

    def get_inherited(self, obj):
        return bool(getattr(obj, '_inherited', False))

    def get_possible_duplicate(self, obj):
        return bool(getattr(obj, '_possible_duplicate', False))

    def _context_owners(self, validated_data):
        application_id = validated_data.pop('application', None)
        experience_id = validated_data.pop('experience', None)
        user = self.context['request'].user
        application = None
        experience = None
        if application_id:
            application = Application.objects.filter(id=application_id, user=user).first()
            if application is None:
                raise serializers.ValidationError({'application': 'Application not found.'})
        if experience_id:
            experience = Experience.objects.filter(id=experience_id, user=user).first()
            if experience is None:
                raise serializers.ValidationError({'experience': 'Experience not found.'})
        return application, experience

    def _add_contexts(self, contact, application, experience):
        records = []
        if application:
            record = ensure_application_career_record(application)
            ContactContext.objects.get_or_create(
                contact=contact,
                application=application,
                experience=None,
                defaults={
                    'career_record': record,
                    'source': 'APPLICATION',
                },
            )
            records.append(record)
        if experience:
            record = ensure_experience_career_record(experience)
            ContactContext.objects.get_or_create(
                contact=contact,
                application=None,
                experience=experience,
                defaults={
                    'career_record': record,
                    'source': 'EXPERIENCE',
                },
            )
            records.append(record)
        return records

    def create(self, validated_data):
        connect_to_self = validated_data.pop('connect_to_self', None)
        relationship_kind = validated_data.pop('relationship_kind', 'CONTACT')
        custom_label = (validated_data.pop('custom_label', '') or '').strip()
        application, experience = self._context_owners(validated_data)
        user = self.context['request'].user
        email = validated_data.get('email', '')

        with transaction.atomic():
            contact = None
            if email:
                contact = Contact.objects.filter(user=user, email__iexact=email).first()
            if contact is None:
                contact = Contact.objects.create(user=user, **validated_data)
            else:
                for field in ['job_title', 'company']:
                    if not getattr(contact, field) and validated_data.get(field):
                        setattr(contact, field, validated_data[field])
                contact.save()

            records = self._add_contexts(contact, application, experience)
            should_connect = bool(application or experience) if connect_to_self is None else connect_to_self
            if should_connect:
                if relationship_kind == 'CUSTOM' and not custom_label:
                    raise serializers.ValidationError({'custom_label': 'Enter a custom relationship.'})
                ContactRelationship.objects.get_or_create(
                    user=user,
                    source_contact=None,
                    target_contact=contact,
                    kind=relationship_kind,
                    custom_label=custom_label if relationship_kind == 'CUSTOM' else '',
                    defaults={'career_record': records[0] if records else None},
                )
            return contact

    def update(self, instance, validated_data):
        validated_data.pop('connect_to_self', None)
        validated_data.pop('relationship_kind', None)
        validated_data.pop('custom_label', None)
        application, experience = self._context_owners(validated_data)
        with transaction.atomic():
            contact = super().update(instance, validated_data)
            self._add_contexts(contact, application, experience)
            return contact

    def to_representation(self, instance):
        data = super().to_representation(instance)
        contexts = list(instance.contexts.all())
        application_context = next((item for item in contexts if item.application_id), None)
        experience_context = next((item for item in contexts if item.experience_id), None)
        data['application'] = application_context.application_id if application_context else None
        data['experience'] = experience_context.experience_id if experience_context else None
        return data
