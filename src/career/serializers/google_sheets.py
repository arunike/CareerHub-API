
from rest_framework import serializers

from ..models import GoogleSheetSyncConfig, GoogleSheetSyncRun


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
        from ..services.google_sheets import get_service_account_email

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
        from ..services.google_sheets import parse_google_sheet_url

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
