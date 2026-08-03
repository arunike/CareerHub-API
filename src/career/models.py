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
    free_food_perk_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    free_food_perk_frequency = models.CharField(max_length=10, choices=VALUE_FREQUENCY_CHOICES, default='YEARLY')
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

class Offer(models.Model):
    EQUITY_LIQUIDITY_CHOICES = [
        ('LIQUID', 'Public or Freely Tradable'),
        ('BUYBACK', 'Private with Company Buyback'),
        ('ILLIQUID', 'Private and Not Sellable'),
    ]

    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='offer')
    
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, help_text="Annual Base Salary")
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Annual Target Bonus")
    equity = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Annualized Equity Value")
    equity_total_grant = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Total equity grant value")
    equity_vesting_percent = models.DecimalField(max_digits=5, decimal_places=2, default=25, help_text="Annual vesting percent used for annualized equity")
    equity_vesting_schedule = models.JSONField(default=list, blank=True, help_text="Four-year equity vesting percentages, e.g. [20, 20, 30, 30]")
    equity_liquidity = models.CharField(max_length=20, choices=EQUITY_LIQUIDITY_CHOICES, default='LIQUID')
    annual_refresh_value = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Optional annual equity refresh grant value. 0 disables refresh modelling.",
    )
    refresh_starts_year = models.SmallIntegerField(
        default=2,
        help_text="First year a refresh grant is issued. Refreshes vest evenly over four years.",
    )
    equity_buyback_value = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Annual equity value realizable through a company buyback")
    sign_on = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="One-time Sign On Bonus")
    benefits_value = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Estimated Annual Benefits Value")
    benefit_items = models.JSONField(default=list, blank=True, help_text="Benefit item breakdown used to derive annual benefits value")
    pto_days = models.IntegerField(default=15)
    is_unlimited_pto = models.BooleanField(default=False, help_text="Offer includes unlimited PTO")
    sick_leave_days = models.IntegerField(default=0)
    sick_leave_included_in_unlimited_pto = models.BooleanField(default=True)
    holiday_days = models.IntegerField(default=11)
    is_current = models.BooleanField(default=False, help_text="Is this your current role?")
    raise_history = models.JSONField(default=list, blank=True, help_text="List of raise events [{id, date, type, base_before, base_after, bonus_before, bonus_after, equity_before, equity_after, label, notes}]")
    deadline = models.DateField(null=True, blank=True)
    final_decision_reasoning = models.TextField(blank=True)
    final_decision_status = models.CharField(max_length=20, default='PENDING')
    negotiation_rounds = models.JSONField(default=list, blank=True)
    risk_notes = models.TextField(blank=True)
    
    health_premium_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Monthly Health Insurance Premium")
    hsa_employer_contribution = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Annual Employer HSA Contribution")
    health_plan_type = models.CharField(max_length=50, blank=True, default='', help_text="Health Plan Type, e.g. HDHP, PPO")
    health_oop_max = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Annual Health Out-of-Pocket Maximum")
    forty_one_k_match_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Employer 401(k) Match Percentage (e.g. 50.00 for 50%)")
    forty_one_k_max_match = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Maximum Employee 401(k) Contribution matched (e.g. 6.00 for 6%)")
    relocation_bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="One-time Relocation or Signing Perk Cash Value")

    # Paycheck Schedule & Benefits Detail
    paychecks_per_year = models.IntegerField(default=26, help_text="Number of paychecks per year (e.g. 26 or 27)")
    health_premium_paycheck = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Medical premium per paycheck")
    dental_premium_paycheck = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Dental premium per paycheck")
    vision_premium_paycheck = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Vision premium per paycheck")
    health_deductible = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    health_family_oop_max = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    health_pcp_copay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    health_specialist_copay = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    dental_plan_name = models.CharField(max_length=100, blank=True, default='')
    dental_monthly_premium = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    dental_annual_max = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    dental_deductible = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vision_plan_name = models.CharField(max_length=100, blank=True, default='')
    vision_monthly_premium = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vision_frames_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vision_contacts_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Dependent Coverage Fields
    has_dependents = models.BooleanField(default=False)
    dependent_coverage_tier = models.CharField(max_length=50, blank=True, default='EMPLOYEE_SPOUSE')
    dependent_count = models.IntegerField(default=0)
    health_family_deductible = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    dependent_health_premium_paycheck = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    dependent_dental_premium_paycheck = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    dependent_vision_premium_paycheck = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Offer for {self.application}"


class OfferDecisionSnapshot(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='offer_decision_snapshots')
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='decision_snapshots')
    title = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    decision_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    rank = models.PositiveSmallIntegerField(null=True, blank=True)
    total_comp = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adjusted_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    commute_cost_annual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_snapshot = models.JSONField(default=dict, blank=True)
    score_categories = models.JSONField(default=list, blank=True)
    offer_snapshot = models.JSONField(default=dict, blank=True)
    adjustment_snapshot = models.JSONField(default=dict, blank=True)
    is_locked = models.BooleanField(default=False)
    captured_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-captured_at']

    def __str__(self):
        return self.title or f"Decision snapshot for offer {self.offer_id}"


class InterviewDebrief(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='interview_debriefs'
    )
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='debriefs'
    )
    # Stage key from the user's configured application_stages, e.g. ROUND_1.
    stage = models.CharField(max_length=50)
    interview_date = models.DateField(null=True, blank=True)
    questions_asked = models.TextField(blank=True)
    went_well = models.TextField(blank=True)
    weak_areas = models.TextField(blank=True)
    interviewer_notes = models.TextField(blank=True)
    # 1-5. Range is enforced in the serializer; no DB CHECK, which this engine rejects.
    confidence = models.SmallIntegerField(null=True, blank=True)
    next_steps = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['interview_date', 'created_at']
        indexes = [models.Index(fields=['user', 'application'], name='career_debrief_app_idx')]

    def __str__(self):
        return f"{self.application.role_title} - {self.stage}"


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


class CareerRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='career_records'
    )
    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        related_name='career_record',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']

    def __str__(self):
        if self.application_id:
            return str(self.application)
        experience = self.experiences.order_by('-is_current', '-start_date', '-id').first()
        return str(experience) if experience else f'Career record {self.id}'


class Contact(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='career_contacts'
    )
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    job_title = models.CharField(max_length=255, blank=True)
    company = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']
        indexes = [
            models.Index(fields=['user', 'name'], name='career_person_name_idx'),
            models.Index(fields=['user', 'email'], name='career_person_email_idx'),
        ]

    def __str__(self):
        return self.name


class ContactContext(models.Model):
    SOURCE_CHOICES = [
        ('APPLICATION', 'Application'),
        ('EXPERIENCE', 'Experience'),
        ('MANUAL', 'Manual'),
    ]

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='contexts')
    career_record = models.ForeignKey(
        CareerRecord, on_delete=models.CASCADE, related_name='contact_contexts'
    )
    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='contact_contexts',
        null=True,
        blank=True,
    )
    experience = models.ForeignKey(
        'Experience',
        on_delete=models.CASCADE,
        related_name='contact_contexts',
        null=True,
        blank=True,
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['career_record', 'contact'], name='career_context_record_idx'),
            models.Index(fields=['application', 'contact'], name='career_context_app_idx'),
            models.Index(fields=['experience', 'contact'], name='career_context_exp_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(application__isnull=False) | models.Q(experience__isnull=False),
                name='contact_context_has_owner',
            ),
        ]


class ContactRelationship(models.Model):
    KIND_CHOICES = [
        ('CONTACT', 'Contact'),
        ('RECRUITER', 'Recruiter'),
        ('INTERVIEWER', 'Interviewer'),
        ('HIRING_MANAGER', 'Hiring Manager'),
        ('MANAGER', 'Manager'),
        ('DIRECT_TEAMMATE', 'Direct Teammate'),
        ('COWORKER', 'Coworker'),
        ('TECH_LEAD', 'Tech Lead'),
        ('MENTOR', 'Mentor'),
        ('WORKS_WITH', 'Works With'),
        ('CUSTOM', 'Custom'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contact_relationships'
    )
    # A null source represents the signed-in user at the center of the graph.
    source_contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name='outgoing_relationships',
        null=True,
        blank=True,
    )
    target_contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name='incoming_relationships'
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES, default='CONTACT')
    custom_label = models.CharField(max_length=80, blank=True)
    career_record = models.ForeignKey(
        CareerRecord,
        on_delete=models.SET_NULL,
        related_name='contact_relationships',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['user', 'source_contact'], name='career_rel_source_idx'),
            models.Index(fields=['user', 'target_contact'], name='career_rel_target_idx'),
        ]

    def __str__(self):
        source = self.source_contact.name if self.source_contact_id else 'Me'
        label = self.custom_label if self.kind == 'CUSTOM' else self.get_kind_display()
        return f'{source} - {label} - {self.target_contact.name}'


class Document(models.Model):
    DOCUMENT_TYPES = [
        ('RESUME', 'Resume'),
        ('COVER_LETTER', 'Cover Letter'),
        ('OFFER_LETTER', 'Offer Letter'),
        ('PORTFOLIO', 'Portfolio'),
        ('OTHER', 'Other'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='documents')
    title = models.CharField(max_length=255)
    file = models.URLField(max_length=2048, null=True, blank=True)
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default='RESUME')
    application = models.ForeignKey(Application, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    root_document = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='versions')
    version_number = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False, help_text="Locked documents cannot be deleted")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} (v{self.version_number})"


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
    documents = models.ManyToManyField(Document, blank=True, related_name='timeline_entries')
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


class AIArtifact(models.Model):
    TYPE_JD_REPORT = 'JD_REPORT'
    TYPE_COVER_LETTER = 'COVER_LETTER'
    TYPE_NEGOTIATION_RESULT = 'NEGOTIATION_RESULT'
    TYPE_PROMOTION_REVIEW = 'PROMOTION_REVIEW'
    ARTIFACT_TYPE_CHOICES = [
        (TYPE_JD_REPORT, 'JD Report'),
        (TYPE_COVER_LETTER, 'Cover Letter'),
        (TYPE_NEGOTIATION_RESULT, 'Negotiation Result'),
        (TYPE_PROMOTION_REVIEW, 'Promotion Review'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_artifacts')
    artifact_type = models.CharField(max_length=40, choices=ARTIFACT_TYPE_CHOICES)
    client_id = models.CharField(max_length=120)
    title = models.CharField(max_length=255, blank=True)
    summary = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    source_application = models.ForeignKey(
        Application,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_artifacts',
    )
    source_offer = models.ForeignKey(
        Offer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_artifacts',
    )
    source_experience = models.ForeignKey(
        'Experience',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name='ai_artifacts',
    )
    is_locked = models.BooleanField(default=False)
    saved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-saved_at', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'client_id'], name='unique_ai_artifact_client_id_per_user'),
        ]

    def __str__(self):
        return self.title or f"{self.artifact_type} {self.client_id}"


class AIArtifactGenerationJob(models.Model):
    STATUS_QUEUED = 'QUEUED'
    STATUS_RUNNING = 'RUNNING'
    STATUS_SUCCEEDED = 'SUCCEEDED'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCEEDED, 'Succeeded'),
        (STATUS_FAILED, 'Failed'),
    ]

    KIND_PROMOTION_REVIEW = 'PROMOTION_REVIEW'
    KIND_CHOICES = [
        (KIND_PROMOTION_REVIEW, 'Promotion Review'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_artifact_generation_jobs')
    kind = models.CharField(max_length=40, choices=KIND_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    input_payload = models.JSONField(default=dict, blank=True)
    result_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    artifact = models.ForeignKey(
        AIArtifact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generation_jobs',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.kind} job {self.id} ({self.status})"


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
        CareerRecord,
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
