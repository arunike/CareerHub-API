from rest_framework import serializers

from .ai_provider import validate_ai_provider_endpoint
from .models import Event, CustomHoliday, AvailabilityOverride, AvailabilitySetting, EventCategory, UserSettings, ConflictAlert, ShareLink, PublicBooking
from career.models import Application

class EventCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EventCategory
        fields = ['id', 'name', 'color', 'icon', 'is_locked']

class EventSerializer(serializers.ModelSerializer):
    category_details = EventCategorySerializer(source='category', read_only=True)
    application_details = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'name', 'date', 'start_time', 'end_time', 'timezone',
            'category', 'category_details', 'color',
            'location_type', 'location', 'meeting_link',
            'is_recurring', 'recurrence_rule', 'parent_event',
            'application', 'application_details',
            'notes', 'reminder_minutes', 'is_locked',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['application'].queryset = Application.objects.filter(user=request.user)
            fields['category'].queryset = EventCategory.objects.filter(user=request.user)
            fields['parent_event'].queryset = Event.objects.filter(user=request.user)
        else:
            fields['application'].queryset = Application.objects.none()
            fields['category'].queryset = EventCategory.objects.none()
            fields['parent_event'].queryset = Event.objects.none()
        return fields

    def get_application_details(self, obj):
        if not obj.application:
            return None
        return {
            'id': obj.application.id,
            'company': obj.application.company.name if obj.application.company else 'Unknown',
            'role': obj.application.role_title,
            'status': obj.application.status
        }

class CustomHolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomHoliday
        fields = ['id', 'date', 'group_id', 'description', 'holiday_type', 'is_recurring', 'is_locked', 'tab']

class AvailabilityOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilityOverride
        fields = ['id', 'date', 'availability_text', 'updated_at']
        read_only_fields = ['updated_at']

class AvailabilitySettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilitySetting
        fields = ['id', 'key', 'value']

class UserSettingsSerializer(serializers.ModelSerializer):
    ai_provider_api_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )
    ai_provider_api_key_configured = serializers.SerializerMethodField()
    ai_provider_api_key_masked = serializers.SerializerMethodField()
    email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = UserSettings
        fields = [
            'id', 'work_start_time', 'work_end_time', 'work_time_ranges', 'work_days',
            'default_event_duration', 'buffer_time', 'primary_timezone',
            'theme', 'notification_preferences', 'global_availability',
            'ghosting_threshold_days', 'default_event_category',
            'ignored_federal_holidays', 'employment_types', 'holiday_tabs', 'application_stages', 'hidden_nav_items',
            'ai_provider_adapter', 'ai_provider_endpoint', 'ai_provider_model', 'ai_provider_api_key',
            'ai_provider_api_key_configured', 'ai_provider_api_key_masked',
            'display_name', 'profile_picture', 'email',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            fields['default_event_category'].queryset = EventCategory.objects.filter(user=request.user)
        else:
            fields['default_event_category'].queryset = EventCategory.objects.none()
        return fields

    def get_ai_provider_api_key_configured(self, obj):
        return obj.has_ai_provider_api_key()

    def get_ai_provider_api_key_masked(self, obj):
        return obj.get_ai_provider_api_key_masked()

    def validate_ai_provider_endpoint(self, value):
        return validate_ai_provider_endpoint(value)

    def create(self, validated_data):
        api_key = validated_data.pop('ai_provider_api_key', None)
        instance = super().create(validated_data)
        if api_key is not None:
            if api_key.strip():
                instance.set_ai_provider_api_key(api_key)
            else:
                instance.clear_ai_provider_api_key()
            instance.save(update_fields=['ai_provider_api_key_encrypted', 'updated_at'])
        return instance

    def update(self, instance, validated_data):
        api_key = validated_data.pop('ai_provider_api_key', None)
        instance = super().update(instance, validated_data)
        if api_key is not None:
            if api_key.strip():
                instance.set_ai_provider_api_key(api_key)
            else:
                instance.clear_ai_provider_api_key()
            instance.save(update_fields=['ai_provider_api_key_encrypted', 'updated_at'])
        return instance


class AIProviderChatMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=['system', 'user', 'assistant'])
    content = serializers.CharField(trim_whitespace=False)


class AIProviderChatCompletionRequestSerializer(serializers.Serializer):
    messages = AIProviderChatMessageSerializer(many=True, allow_empty=False)
    temperature = serializers.FloatField(required=False, min_value=0, max_value=2)

class ConflictAlertSerializer(serializers.ModelSerializer):
    event1_details = EventSerializer(source='event1', read_only=True)
    event2_details = EventSerializer(source='event2', read_only=True)
    
    class Meta:
        model = ConflictAlert
        fields = ['id', 'event1', 'event2', 'event1_details', 'event2_details', 'detected_at', 'resolved']
        read_only_fields = ['detected_at']

class ShareLinkSerializer(serializers.ModelSerializer):
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = ShareLink
        fields = [
            'id',
            'uuid',
            'title',
            'host_display_name',
            'host_email',
            'public_note',
            'duration_days',
            'booking_block_minutes',
            'buffer_minutes',
            'max_bookings_per_day',
            'created_at',
            'expires_at',
            'is_active',
            'is_expired',
            'is_locked',
        ]
        read_only_fields = ['created_at', 'is_expired']


class PublicBookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PublicBooking
        fields = [
            'id',
            'share_link',
            'share_link_title',
            'name',
            'email',
            'date',
            'start_time',
            'end_time',
            'timezone',
            'notes',
            'is_locked',
            'created_at',
        ]
        read_only_fields = ['created_at']

    share_link_title = serializers.CharField(source='share_link.title', read_only=True)
