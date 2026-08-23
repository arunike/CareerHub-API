import re
from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class GoogleSheetSyncConfig(models.Model):
    TARGET_APPLICATIONS = 'APPLICATIONS'
    TARGET_EVENTS = 'EVENTS'
    MISSING_ROW_IGNORE = 'IGNORE'
    MISSING_ROW_ARCHIVE_THEN_DELETE = 'ARCHIVE_THEN_DELETE'
    TARGET_CHOICES = [
        (TARGET_APPLICATIONS, 'Applications'),
        (TARGET_EVENTS, 'Events'),
    ]
    MISSING_ROW_CHOICES = [
        (MISSING_ROW_IGNORE, 'Ignore missing rows'),
        (MISSING_ROW_ARCHIVE_THEN_DELETE, 'Archive then delete missing rows'),
    ]

    STATUS_IDLE = 'IDLE'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_ERROR = 'ERROR'
    STATUS_CHOICES = [
        (STATUS_IDLE, 'Idle'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_ERROR, 'Error'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='google_sheet_sync_configs')
    name = models.CharField(max_length=120)
    sheet_url = models.URLField(max_length=2048)
    spreadsheet_id = models.CharField(max_length=255, blank=True)
    worksheet_name = models.CharField(max_length=255, blank=True)
    gid = models.CharField(max_length=64, blank=True)
    target_type = models.CharField(max_length=20, choices=TARGET_CHOICES)
    column_mapping = models.JSONField(default=dict, blank=True)
    overwrite_strategies = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    sync_time = models.TimeField(default=time(22, 0), help_text='Preferred daily sync time in sync_timezone.')
    sync_timezone = models.CharField(max_length=64, default='America/Los_Angeles')
    header_row = models.PositiveSmallIntegerField(default=1)
    missing_row_strategy = models.CharField(
        max_length=30,
        choices=MISSING_ROW_CHOICES,
        default=MISSING_ROW_ARCHIVE_THEN_DELETE,
    )
    missing_row_delete_after_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IDLE)
    last_error = models.TextField(blank=True)
    last_result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', '-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='unique_google_sheet_sync_name_per_user'),
        ]

    def __str__(self):
        return f"{self.name} -> {self.target_type}"


class GoogleSheetSyncRun(models.Model):
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_ERROR = 'ERROR'
    STATUS_ROLLED_BACK = 'ROLLED_BACK'
    STATUS_CHOICES = [
        (STATUS_SUCCESS, 'Success'),
        (STATUS_ERROR, 'Error'),
        (STATUS_ROLLED_BACK, 'Rolled Back'),
    ]

    config = models.ForeignKey(GoogleSheetSyncConfig, on_delete=models.CASCADE, related_name='runs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    changes = models.JSONField(default=list, blank=True)
    error_details = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.config.name} Run at {self.started_at}"


class GoogleSheetSyncRow(models.Model):
    config = models.ForeignKey(GoogleSheetSyncConfig, on_delete=models.CASCADE, related_name='tracked_rows')
    external_key = models.CharField(max_length=255)
    row_number = models.PositiveIntegerField()
    row_hash = models.CharField(max_length=64)
    local_object_type = models.CharField(max_length=50)
    local_object_id = models.PositiveIntegerField()
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['config', 'external_key'], name='unique_google_sheet_row_per_config'),
        ]

    def __str__(self):
        return f"{self.config_id}:{self.external_key}"


class GoogleOAuthCredential(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='google_oauth_credential')
    google_email = models.EmailField(blank=True)
    scopes = models.JSONField(default=list, blank=True)
    refresh_token_encrypted = models.TextField(blank=True, default='')
    token_uri = models.URLField(default='https://oauth2.googleapis.com/token')
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Google OAuth for {self.user_id}"


class GoogleOAuthState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='google_oauth_states')
    state = models.CharField(max_length=128, unique=True)
    redirect_url = models.URLField(max_length=2048, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Google OAuth state for {self.user_id}"
