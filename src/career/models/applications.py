import re
from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Company(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='companies')
    name = models.CharField(max_length=255)
    website = models.URLField(blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Companies"
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='unique_company_per_user'),
        ]

    def __str__(self):
        return self.name


class Application(models.Model):
    RTO_CHOICES = [
        ('REMOTE', 'Remote'),
        ('HYBRID', 'Hybrid'),
        ('ONSITE', 'Onsite'),
        ('UNKNOWN', 'Unknown'),
    ]
    VALUE_FREQUENCY_CHOICES = [
        ('DAILY', 'Daily'),
        ('MONTHLY', 'Monthly'),
        ('YEARLY', 'Yearly'),
    ]
    VISA_SPONSORSHIP_CHOICES = [
        ('', 'Not specified'),
        ('NOT_NEEDED', 'Not needed'),
        ('AVAILABLE', 'Sponsorship available'),
        ('TRANSFER_ONLY', 'Transfer only'),
        ('NOT_AVAILABLE', 'No sponsorship'),
    ]
    DAY_ONE_GC_CHOICES = [
        ('', 'Not specified'),
        ('YES', 'Yes'),
        ('NO', 'No'),
        ('NOT_APPLICABLE', 'Not applicable'),
    ]
    FLEXIBLE_HOURS_CHOICES = [
        ('FLEXIBLE', 'Flexible Hours'),
        ('CORE_HOURS', 'Core Hours'),
        ('STRICT', 'Strict Hours'),
        ('UNKNOWN', 'Unknown'),
    ]
    TRAVEL_FREQUENCY_CHOICES = [
        ('NONE', 'No Travel'),
        ('LOW', 'Low Travel (<10%)'),
        ('MEDIUM', 'Medium Travel (10-25%)'),
        ('HIGH', 'High Travel (>25%)'),
        ('UNKNOWN', 'Unknown'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='applications')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='applications')
    role_title = models.CharField(max_length=255)
    job_link = models.URLField(blank=True, null=True)
    status = models.CharField(max_length=50, default='APPLIED')
    
    # Details
    rto_policy = models.CharField(max_length=20, choices=RTO_CHOICES, default='UNKNOWN')
    rto_days_per_week = models.PositiveSmallIntegerField(default=0)
    commute_cost_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commute_cost_frequency = models.CharField(max_length=10, choices=VALUE_FREQUENCY_CHOICES, default='MONTHLY')
    # [{mode, minutes_each_way, cost_value, cost_frequency, cost_mode, miles_each_way, distance_basis, mpg, gas_price_per_gallon, parking_tolls_per_day, is_primary}]
    commute_options = models.JSONField(default=list, blank=True, help_text="Per-mode commute entries used for time and cost comparison")
    # Legacy flat figure, kept so offers saved before the per-meal fields keep their value.
    free_food_perk_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    free_food_perk_frequency = models.CharField(max_length=10, choices=VALUE_FREQUENCY_CHOICES, default='YEARLY')
    # Which meals the office provides, e.g. ["LUNCH", "DINNER"], against the RTO office days.
    free_food_meals = models.JSONField(
        default=list, blank=True, help_text="Meals provided on an office day"
    )
    free_food_value_per_meal = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    tax_base_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tax_bonus_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tax_equity_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    monthly_rent_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salary_range = models.CharField(max_length=100, blank=True, help_text="e.g. $150k - $180k")
    location = models.CharField(max_length=100, blank=True)
    office_location = models.CharField(max_length=100, blank=True)
    visa_sponsorship = models.CharField(max_length=20, choices=VISA_SPONSORSHIP_CHOICES, blank=True, default='')
    day_one_gc = models.CharField(max_length=20, choices=DAY_ONE_GC_CHOICES, blank=True, default='')
    growth_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Manual growth score from 1 to 5",
    )
    work_life_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Manual work-life balance score from 1 to 5",
    )
    brand_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Manual company brand score from 1 to 5",
    )
    team_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Manual manager/team score from 1 to 5",
    )
    
    employment_type = models.CharField(max_length=20, default='full_time', null=True, blank=True)
    level = models.CharField(max_length=50, blank=True, default='', help_text="Job level or band, e.g. L5, Senior, Staff, IC3")
    flexible_hours_policy = models.CharField(max_length=20, choices=FLEXIBLE_HOURS_CHOICES, default='UNKNOWN')
    travel_frequency = models.CharField(max_length=20, choices=TRAVEL_FREQUENCY_CHOICES, default='UNKNOWN')

    submitted_documents = models.ManyToManyField(
        'Document',
        blank=True,
        related_name='submitted_for_applications',
        help_text="Exact document versions sent with this application; a later version does not replace them",
    )
    job_description = models.TextField(
        blank=True,
        help_text="Full job posting text, kept because postings are taken down while you interview",
    )
    notes = models.TextField(blank=True)
    current_round = models.IntegerField(default=0, help_text="Current interview round number (0 for none)")
    is_locked = models.BooleanField(default=False, help_text="Locked applications cannot be deleted")
    source_removed_at = models.DateTimeField(null=True, blank=True)
    source_removed_delete_after = models.DateTimeField(null=True, blank=True)
    source_removed_previous_status = models.CharField(max_length=50, blank=True)
    
    date_applied = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=['user', 'status', 'date_applied'],
                name='career_app_ghost_idx',
            ),
        ]

    def __str__(self):
        return f"{self.role_title} at {self.company.name}"


class ApplicationContact(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='application_contacts'
    )
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='contacts', null=True, blank=True
    )
    experience = models.ForeignKey(
        'Experience', on_delete=models.CASCADE, related_name='contacts', null=True, blank=True
    )
    # Often all you have at first is a name on a calendar invite.
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False, help_text="Locked contacts cannot be deleted")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['user', 'application'], name='career_contact_app_idx'),
            models.Index(fields=['user', 'experience'], name='career_contact_exp_idx'),
        ]
        constraints = [
            # A contact with no owner would be unreachable from any screen.
            models.CheckConstraint(
                check=models.Q(application__isnull=False) | models.Q(experience__isnull=False),
                name='contact_has_application_or_experience',
            )
        ]

    def __str__(self):
        return self.name


DEFAULT_TIMELINE_STAGE_ORDER = {
    'APPLIED': 0,
    'OA': 10,
    'SCREEN': 20,
    'FINAL_ROUND': 890,
    'ONSITE': 900,
    'OFFER': 1000,
    'REJECTED': 1010,
    'GHOSTED': 1020,
    'REMOVED_FROM_SHEET': 1030,
}


def application_timeline_stage_order(stage, configured_stages=None):
    round_match = re.match(r'^ROUND_(\d+)$', stage or '')
    if round_match:
        return 30 + (int(round_match.group(1)) - 1) * 10

    if stage in DEFAULT_TIMELINE_STAGE_ORDER:
        return DEFAULT_TIMELINE_STAGE_ORDER[stage]

    if configured_stages:
        order_map = {s['key']: idx * 10 for idx, s in enumerate(configured_stages)}
        if stage in order_map:
            return order_map[stage]

    return 999


class ApplicationTimelineEntry(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='application_timeline_entries')
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='timeline_entries')
    stage = models.CharField(max_length=50)
    stage_order = models.PositiveSmallIntegerField(default=999)
    display_title = models.CharField(max_length=120, blank=True)
    event_date = models.DateField(null=True, blank=True)
    event_date_is_user_override = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    notes_is_user_override = models.BooleanField(default=False)
    deleted_by_user_at = models.DateTimeField(null=True, blank=True)
    hidden_by_sync_at = models.DateTimeField(null=True, blank=True)
    documents = models.ManyToManyField('career.Document', blank=True, related_name='timeline_entries')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['application_id', 'stage_order']
        constraints = [
            models.UniqueConstraint(fields=['user', 'application', 'stage'], name='unique_timeline_stage_per_application'),
        ]

    def save(self, *args, **kwargs):
        settings_profile = getattr(self.user, 'availability_settings_profile', None)
        stages = settings_profile.application_stages if settings_profile and settings_profile.application_stages else []
        self.stage_order = application_timeline_stage_order(self.stage, stages)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.stage} for {self.application}"


class Task(models.Model):
    STATUS_CHOICES = [
        ('TODO', 'To Do'),
        ('IN_PROGRESS', 'In Progress'),
        ('DONE', 'Done'),
    ]

    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='tasks')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='TODO')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    due_date = models.DateField(null=True, blank=True)
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', 'position', '-updated_at']

    def __str__(self):
        return self.title
