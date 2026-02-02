from rest_framework import serializers
from .models import Event, CustomHoliday, AvailabilityOverride, AvailabilitySetting, EventCategory, UserSettings, ConflictAlert, ShareLink
from career.models import Application

class EventCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EventCategory
        fields = ['id', 'name', 'color', 'icon']

class EventSerializer(serializers.ModelSerializer):
    category_details = EventCategorySerializer(source='category', read_only=True)
    
    # Application Linking
    application = serializers.PrimaryKeyRelatedField(
        queryset=Application.objects.all(),
        required=False,
        allow_null=True
    )
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
        fields = ['id', 'date', 'description', 'is_recurring', 'is_locked']

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
    class Meta:
        model = UserSettings
        fields = [
            'id', 'work_start_time', 'work_end_time', 'work_days',
            'default_event_duration', 'buffer_time', 'primary_timezone',
            'theme', 'notification_preferences', 'global_availability',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

class ConflictAlertSerializer(serializers.ModelSerializer):
    event1_details = EventSerializer(source='event1', read_only=True)
    event2_details = EventSerializer(source='event2', read_only=True)
    
    class Meta:
        model = ConflictAlert
        fields = ['id', 'event1', 'event2', 'event1_details', 'event2_details', 'detected_at', 'resolved']
        read_only_fields = ['detected_at']

class ShareLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShareLink
        fields = ['id', 'uuid', 'title', 'duration_days', 'created_at', 'expires_at', 'is_active']
        read_only_fields = ['created_at']
