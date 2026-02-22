from django.db import models
import json
from django.utils import timezone

class EventCategory(models.Model):
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=7)
    icon = models.CharField(max_length=50, blank=True)
    
    class Meta:
        verbose_name_plural = 'Event Categories'
    
    def __str__(self):
        return self.name

class CustomHoliday(models.Model):
    date = models.DateField(unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    is_recurring = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False, help_text="Locked holidays cannot be deleted")

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
    THEME_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('auto', 'Auto'),
    ]
    
    work_start_time = models.TimeField(default='09:00:00')
    work_end_time = models.TimeField(default='17:00:00')
    work_days = models.JSONField(default=list)
    default_event_duration = models.IntegerField(default=60)
    buffer_time = models.IntegerField(default=0)
    primary_timezone = models.CharField(max_length=50, default='America/Los_Angeles')
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default='light')
    notification_preferences = models.JSONField(default=dict)
    global_availability = models.JSONField(default=dict)
    ghosting_threshold_days = models.IntegerField(default=30, help_text="Days of inactivity before marking application as ghosted")
    default_event_category = models.ForeignKey(EventCategory, on_delete=models.SET_NULL, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = 'User Settings'
    
    def __str__(self):
        return f"Settings (Updated: {self.updated_at})"

class ConflictAlert(models.Model):
    event1 = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='conflicts_as_event1')
    event2 = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='conflicts_as_event2')
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Conflict: {self.event1.name} vs {self.event2.name}"

class ShareLink(models.Model):
    uuid = models.CharField(max_length=36, unique=True)
    title = models.CharField(max_length=255)
    duration_days = models.IntegerField(default=7)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'start_time']
        unique_together = ('share_link', 'date', 'start_time', 'end_time')

    def __str__(self):
        return f"{self.name} booking on {self.date} {self.start_time}-{self.end_time}"

class AvailabilityOverride(models.Model):
    date = models.DateField(unique=True)
    availability_text = models.CharField(max_length=500)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Override {self.date}: {self.availability_text}"

class AvailabilitySetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=255)
    
    def __str__(self):
        return f"{self.key}: {self.value}"
