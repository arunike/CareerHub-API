import re
from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Offer(models.Model):
    EQUITY_LIQUIDITY_CHOICES = [
        ('LIQUID', 'Public or Freely Tradable'),
        ('BUYBACK', 'Private with Company Buyback'),
        ('ILLIQUID', 'Private and Not Sellable'),
    ]

    application = models.OneToOneField('career.Application', on_delete=models.CASCADE, related_name='offer')
    
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, help_text="Annual Base Salary")
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Annual Target Bonus")
    equity = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Annualized Equity Value")
    equity_total_grant = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Total equity grant value")
    equity_vesting_percent = models.DecimalField(max_digits=5, decimal_places=2, default=25, help_text="Annual vesting percent used for annualized equity")
    equity_vesting_schedule = models.JSONField(default=list, blank=True, help_text="Four-year equity vesting percentages, e.g. [20, 20, 30, 30]")
    equity_liquidity = models.CharField(max_length=20, choices=EQUITY_LIQUIDITY_CHOICES, default='LIQUID')
    equity_cliff_months = models.PositiveSmallIntegerField(default=12, db_default=12, help_text="Months before the first equity vests")
    equity_vests_per_year = models.PositiveSmallIntegerField(default=4, db_default=4, help_text="Vest occasions per year, e.g. 2 for twice a year")
    equity_vesting_years = models.PositiveSmallIntegerField(default=4, db_default=4, help_text="Years over which the initial grant vests")
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
    # Per-year sign-on amounts, e.g. [30000, 20000]. Empty means it is all paid in year 1.
    sign_on_schedule = models.JSONField(default=list, blank=True)
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
        'career.Application', on_delete=models.CASCADE, related_name='debriefs'
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
