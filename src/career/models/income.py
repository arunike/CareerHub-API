import re
from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class IncomeYear(models.Model):
    """Employee elections for a tax year. Pay, premiums and match come from the offer."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='income_years')
    tax_year = models.PositiveIntegerField()
    source_key = models.CharField(max_length=64, default='', help_text="Which role these elections belong to, e.g. experience-10 or offer-3")
    offer = models.ForeignKey('Offer', null=True, blank=True, on_delete=models.SET_NULL, related_name='income_years')
    experience = models.ForeignKey('Experience', null=True, blank=True, on_delete=models.SET_NULL, related_name='income_years')

    first_pay_date = models.DateField(null=True, blank=True, help_text="Anchors pay periods to real dates so vests land in the right one")
    salary_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    paychecks_per_year_override = models.PositiveSmallIntegerField(null=True, blank=True)

    pretax_401k_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    roth_401k_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    hsa_per_period = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fsa_per_period = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    post_tax_deductions_per_period = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Null means fall back to the linked offer's premium for that line.
    medical_premium_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    dental_premium_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    vision_premium_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    dependent_premium_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    custom_deductions = models.JSONField(default=list, blank=True, help_text="[{id, label, amount, treatment}] where treatment is SECTION_125, PRETAX_INCOME_ONLY or POST_TAX")
    period_deductions = models.JSONField(default=list, blank=True, help_text="[{periodIndex, medical, dental, vision, dependent, pretax401kPercent, roth401kPercent, customAmounts}] overrides for a single paycheck")
    # Which pay the plan defers and matches on. Replaced a boolean that could only carve out
    # allowances, leaving no way to say a plan excludes the bonus — the commonest carve-out.
    deferral_base = models.CharField(max_length=20, null=True, blank=True, default='ALL', help_text="Pay the 401(k) defers and matches on: ALL, NO_ALLOWANCES or SALARY_ONLY")
    match_tiers = models.JSONField(default=list, blank=True, help_text="[{id, matchPercent, uptoPercent}] employer 401(k) match bands, e.g. 100% to 3% then 50% to 5%")
    match_non_elective_percent = models.DecimalField(max_digits=6, decimal_places=3, default=0, help_text="Employer contribution paid regardless of deferral, e.g. a safe-harbor 3%")
    match_annual_cap = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Dollar ceiling on the employer's yearly contribution. 0 means none.")
    allowances = models.JSONField(default=list, blank=True, help_text="[{id, label, amount, treatment, timesPer, unit, payOn, payPeriodIndex}] allowances; unit is PAYCHECK, MONTH, YEAR or ONCE; payPeriodIndex names the paycheck a ONCE allowance lands on")
    retirement_starting_balance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="401(k) balance at the start of the tax year")
    retirement_current_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Current 401(k) balance, used to derive investment gains")
    hsa_family_coverage = models.BooleanField(default=False)
    age_50_plus = models.BooleanField(default=False, help_text="Enables the 401(k) catch-up limit")

    include_bonus = models.BooleanField(default=False, help_text="Off by default: a bonus only lands once its payout schedule is set")
    bonus_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Annual bonus. Null falls back to the offer's target bonus.")
    bonus_payouts = models.JSONField(default=list, blank=True, help_text="[{id, periodIndex, payDate, percent}] shares of the bonus. payDate means paid off-cycle.")
    bonus_multiplier_percent = models.DecimalField(max_digits=6, decimal_places=2, default=100, help_text="Company performance multiplier applied to the target bonus")
    bonus_extras = models.JSONField(default=list, blank=True, help_text="[{id, label, amount}] discretionary bonuses stacked on top of the target")
    bonus_prorated = models.BooleanField(default=True, help_text="Scale the target bonus by the share of the performance year the role covers")
    bonus_performance_year = models.PositiveIntegerField(null=True, blank=True, help_text="Year the bonus was earned. Null means the year before it is paid.")
    include_vest_events = models.BooleanField(default=False, help_text="Off by default: vest events are only generated once the vesting terms are confirmed")
    total_grant_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    vests_per_year_override = models.PositiveSmallIntegerField(null=True, blank=True)
    cliff_months_override = models.PositiveSmallIntegerField(null=True, blank=True)
    vesting_years_override = models.PositiveSmallIntegerField(null=True, blank=True)
    first_vest_date = models.DateField(null=True, blank=True, help_text="Grant or first vest date. Defaults to the role start date.")
    income_events = models.JSONField(default=list, blank=True, help_text="[{id, kind, periodIndex, amount, label}] where kind is bonus, vest or other")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'tax_year', 'source_key')
        ordering = ['-tax_year']

    def __str__(self):
        return f"Income year {self.tax_year} for {self.user_id}"


class PaycheckActual(models.Model):
    """A real paycheck, recorded to measure how far the model drifts from reality."""

    income_year = models.ForeignKey(IncomeYear, on_delete=models.CASCADE, related_name='actuals')
    period_index = models.PositiveSmallIntegerField(help_text="1-based pay period")
    pay_date = models.DateField(null=True, blank=True)
    # Only gross and take-home are recorded; the per-line tax columns held no production rows.
    actual_gross = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_net = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    note = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('income_year', 'period_index')
        ordering = ['period_index']

    def __str__(self):
        return f"Paycheck {self.period_index} of {self.income_year_id}"
