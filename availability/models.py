from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .ai_provider import (
    AI_PROVIDER_ADAPTER_CHOICES,
    DEFAULT_AI_PROVIDER_ADAPTER,
    DEFAULT_AI_PROVIDER_ENDPOINT,
    DEFAULT_AI_PROVIDER_MODEL,
    decrypt_ai_provider_secret,
    encrypt_ai_provider_secret,
    mask_ai_provider_secret,
)

class EventCategory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='event_categories')
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7)
    icon = models.CharField(max_length=50, blank=True)
    is_locked = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = 'Event Categories'
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='unique_event_category_per_user'),
        ]
    
    def __str__(self):
        return self.name

class CustomHoliday(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='custom_holidays')
    date = models.DateField()
    group_id = models.CharField(max_length=50, blank=True, null=True, help_text="Group UUID for multi-day holidays")
    description = models.CharField(max_length=255, blank=True, null=True)
    holiday_type = models.CharField(max_length=20, default='custom')
    is_recurring = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False, help_text="Locked holidays cannot be deleted")
    tab = models.CharField(max_length=100, blank=True, null=True, help_text="Custom tab id this holiday belongs to")

    def __str__(self):
        return f"{self.date} - {self.description or 'Holiday'}"

class Event(models.Model):
    TIMEZONE_CHOICES = [
        ('PT', 'Pacific Time'),
        ('ET', 'Eastern Time'),
        ('CT', 'Central Time'),
        ('MT', 'Mountain Time'),
    ]
    
    LOCATION_TYPE_CHOICES = [
        ('in_person', 'In-Person'),
        ('virtual', 'Virtual'),
        ('hybrid', 'Hybrid'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='events')
    name = models.CharField(max_length=255)
    date = models.DateField()
    start_time = models.CharField(max_length=20) 
    end_time = models.CharField(max_length=20)
    timezone = models.CharField(max_length=2, choices=TIMEZONE_CHOICES, default='PT')
    
    category = models.ForeignKey(EventCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    color = models.CharField(max_length=7, blank=True, null=True)
    
    location_type = models.CharField(max_length=20, choices=LOCATION_TYPE_CHOICES, default='virtual')
    location = models.CharField(max_length=500, blank=True)
    meeting_link = models.URLField(max_length=500, blank=True)
    
    is_recurring = models.BooleanField(default=False)
    recurrence_rule = models.JSONField(null=True, blank=True)
    parent_event = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='instances')
    
    # Link to Job Application
    application = models.ForeignKey('career.Application', on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    
    notes = models.TextField(blank=True)
    reminder_minutes = models.IntegerField(default=15)
    
    is_locked = models.BooleanField(default=False, help_text="Locked events cannot be deleted")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'start_time']

    def __str__(self):
        return f"{self.name} ({self.date})"

class UserSettings(models.Model):
    ACCOUNT_DELETION_GRACE_DAYS = 14

    THEME_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('auto', 'Auto'),
    ]
    
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='availability_settings_profile')
    work_start_time = models.TimeField(default='09:00:00')
    work_end_time = models.TimeField(default='17:00:00')
    work_time_ranges = models.JSONField(default=list, blank=True, help_text="List of time ranges [{start: 'HH:MM:SS', end: 'HH:MM:SS'}]. Overrides work_start_time/work_end_time when non-empty.")
    work_days = models.JSONField(default=list)
    default_event_duration = models.IntegerField(default=60)
    buffer_time = models.IntegerField(default=0)
    primary_timezone = models.CharField(max_length=50, default='America/Los_Angeles')
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default='light')
    notification_preferences = models.JSONField(default=dict)
    global_availability = models.JSONField(default=dict)
    ghosting_threshold_days = models.IntegerField(default=30, help_text="Days of inactivity before marking application as ghosted")
    default_event_category = models.ForeignKey(EventCategory, on_delete=models.SET_NULL, null=True, blank=True)
    ignored_federal_holidays = models.JSONField(default=list, help_text="List of federal holiday names or dates to ignore")
    employment_types = models.JSONField(default=list, blank=True, help_text="Custom employment type definitions [{value, label, color}]")
    holiday_tabs = models.JSONField(default=list, blank=True, help_text="User-defined holiday tab definitions [{id, name}]")
    application_stages = models.JSONField(default=list, blank=True, help_text="Custom application timeline stages [{key, label, shortLabel, tone}]")
    hidden_nav_items = models.JSONField(default=list, blank=True, help_text="List of nav route keys to hide from sidebar")
    ai_provider_adapter = models.CharField(
        max_length=32,
        choices=AI_PROVIDER_ADAPTER_CHOICES,
        default=DEFAULT_AI_PROVIDER_ADAPTER,
        help_text="Provider protocol used by the authenticated user's BYOK configuration.",
    )
    ai_provider_endpoint = models.URLField(
        max_length=500,
        blank=True,
        default=DEFAULT_AI_PROVIDER_ENDPOINT,
        help_text="Stored AI provider endpoint for the authenticated user's BYOK configuration.",
    )
    ai_provider_model = models.CharField(
        max_length=255,
        blank=True,
        default=DEFAULT_AI_PROVIDER_MODEL,
        help_text="Stored AI provider model name for the authenticated user's BYOK configuration.",
    )
    ai_provider_api_key_encrypted = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted AI provider API key for the authenticated user.",
    )
    account_deletion_requested_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the authenticated user requested account deletion.",
    )
    account_deletion_scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the account becomes eligible for permanent deletion.",
    )
    
    # Profile information
    display_name = models.CharField(max_length=120, blank=True, help_text="Public display name for booking links")
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True, help_text="Public profile picture for booking links")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = 'User Settings'
    
    def __str__(self):
        return f"Settings (Updated: {self.updated_at})"

    def set_ai_provider_api_key(self, value):
        self.ai_provider_api_key_encrypted = encrypt_ai_provider_secret(value)

    def clear_ai_provider_api_key(self):
        self.ai_provider_api_key_encrypted = ""

    def get_ai_provider_api_key(self):
        return decrypt_ai_provider_secret(self.ai_provider_api_key_encrypted)

    def has_ai_provider_api_key(self):
        return bool(self.ai_provider_api_key_encrypted)

    def get_ai_provider_api_key_masked(self):
        if not self.ai_provider_api_key_encrypted:
            return ""
        try:
            return mask_ai_provider_secret(self.get_ai_provider_api_key())
        except Exception:
            return "Saved key"

    @property
    def account_deletion_pending(self):
        return self.account_deletion_scheduled_for is not None

    def schedule_account_deletion(self, requested_at=None):
        requested_at = requested_at or timezone.now()
        self.account_deletion_requested_at = requested_at
        self.account_deletion_scheduled_for = requested_at + timedelta(days=self.ACCOUNT_DELETION_GRACE_DAYS)

    def cancel_account_deletion(self):
        self.account_deletion_requested_at = None
        self.account_deletion_scheduled_for = None

class ConflictAlert(models.Model):
    event1 = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='conflicts_as_event1')
    event2 = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='conflicts_as_event2')
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Conflict: {self.event1.name} vs {self.event2.name}"

class ShareLink(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='share_links')
    uuid = models.CharField(max_length=36, unique=True)
    title = models.CharField(max_length=255)
    host_display_name = models.CharField(max_length=120, blank=True)
    host_email = models.EmailField(blank=True, null=True)
    public_note = models.TextField(blank=True)
    duration_days = models.IntegerField(default=7)
    booking_block_minutes = models.IntegerField(default=30)
    buffer_minutes = models.IntegerField(default=0)
    max_bookings_per_day = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False, help_text="Locked links cannot be deleted")

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()
    
    def __str__(self):
        return f"Share Link: {self.title}"


class PublicBooking(models.Model):
    share_link = models.ForeignKey(ShareLink, on_delete=models.CASCADE, related_name='bookings')
    name = models.CharField(max_length=120)
    email = models.EmailField()
    date = models.DateField()
    start_time = models.CharField(max_length=20)
    end_time = models.CharField(max_length=20)
    timezone = models.CharField(max_length=2, default='PT')
    notes = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False, help_text="Locked bookings cannot be deleted")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'start_time']
        unique_together = ('share_link', 'date', 'start_time', 'end_time')

    def __str__(self):
        return f"{self.name} booking on {self.date} {self.start_time}-{self.end_time}"

class AvailabilityOverride(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='availability_overrides')
    date = models.DateField()
    availability_text = models.CharField(max_length=500)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'date'], name='unique_availability_override_per_user'),
        ]

    def __str__(self):
        return f"Override {self.date}: {self.availability_text}"

class AvailabilitySetting(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='availability_key_settings')
    key = models.CharField(max_length=100)
    value = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'key'], name='unique_availability_setting_per_user'),
        ]
    
    def __str__(self):
        return f"{self.key}: {self.value}"
