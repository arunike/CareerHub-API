import re
from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Experience(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='experiences')
    title = models.CharField(max_length=255)
    company = models.CharField(max_length=255)
    level = models.CharField(max_length=50, blank=True, default='', help_text="Job level or band, e.g. L5, Senior, Staff, IC3")
    location = models.CharField(max_length=255, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    skills = models.JSONField(default=list, blank=True)
    logo = models.URLField(max_length=2048, null=True, blank=True)
    employment_type = models.CharField(max_length=20, default='full_time', null=True, blank=True)
    is_promotion = models.BooleanField(default=False, help_text="Groups this role with the previous role at the same company as a promotion")
    is_return_offer = models.BooleanField(default=False, help_text="Marks this role as having originated from a return internship offer")
    is_locked = models.BooleanField(default=False, null=True, blank=True, help_text="Locked roles cannot be edited or deleted")
    offer = models.ForeignKey('Offer', null=True, blank=True, on_delete=models.SET_NULL, related_name='experiences', help_text="Linked offer for raise history tracking")
    career_record = models.ForeignKey(
        'career.CareerRecord',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='experiences',
        db_constraint=False,
    )
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Hourly pay rate (for internships)")
    hours_per_day = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Typical hours worked per day for hourly roles")
    working_days_per_week = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, help_text="Typical working days per week for hourly roles")
    total_hours_worked = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Optional manual override for total hours worked in an hourly role")
    overtime_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Optional overtime hours worked in an hourly role")
    overtime_rate = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Optional explicit overtime hourly rate")
    overtime_multiplier = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Optional overtime multiplier when overtime rate is derived from hourly rate")
    total_earnings_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Optional manual override for total internship earnings")
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Annual base salary")
    bonus = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Annual target bonus")
    equity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Annualized equity value")
    work_email = models.EmailField(blank=True, help_text="Your work email address at this job")
    team_history = models.JSONField(default=list, blank=True, help_text="List of team entries [{id, name, start_date, end_date, is_current, norms}]")
    schedule_phases = models.JSONField(default=list, blank=True, help_text="List of schedule phases [{id, name, start_date, end_date, is_current, hourly_rate, hours_per_day, working_days_per_week, total_hours_worked, overtime_hours, overtime_rate, overtime_multiplier, total_earnings_override}]")
    is_pinned = models.BooleanField(default=False, help_text="Pinned experiences appear at the top of the list")
    position = models.PositiveIntegerField(default=0, blank=True, null=True, help_text="Custom display order position")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date', '-created_at']

    def __str__(self):
        return f"{self.title} at {self.company}"
