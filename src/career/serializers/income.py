
from rest_framework import serializers

from ..models import TaxProfile, IncomeYear, PaycheckActual


class PaycheckActualSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaycheckActual
        fields = [
            'id', 'income_year', 'period_index', 'pay_date',
            'actual_gross', 'actual_federal_tax', 'actual_state_tax',
            'actual_social_security', 'actual_medicare', 'actual_net', 'note',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class TaxProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxProfile
        fields = [
            'id', 'tax_year', 'filing_status', 'state', 'locality',
            'w4_dependents_credit', 'w4_other_income', 'w4_deductions',
            'w4_extra_withholding_per_period', 'state_flat_rate_override',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class IncomeYearSerializer(serializers.ModelSerializer):
    actuals = PaycheckActualSerializer(many=True, read_only=True)

    class Meta:
        model = IncomeYear
        fields = [
            'id', 'tax_year', 'source_key', 'offer', 'experience', 'first_pay_date',
            'salary_override', 'paychecks_per_year_override',
            'pretax_401k_percent', 'roth_401k_percent', 'hsa_per_period', 'fsa_per_period',
            'post_tax_deductions_per_period', 'hsa_family_coverage', 'age_50_plus',
            'medical_premium_override', 'dental_premium_override', 'vision_premium_override',
            'dependent_premium_override', 'custom_deductions', 'period_deductions',
            'match_tiers', 'match_non_elective_percent', 'match_annual_cap',
            'exclude_allowances_from_deferral_base', 'allowances',
            'retirement_starting_balance', 'retirement_current_value',
            'include_bonus', 'bonus_override', 'bonus_payouts',
            'bonus_multiplier_percent', 'bonus_extras', 'bonus_prorated',
            'bonus_performance_year',
            'include_vest_events', 'total_grant_override', 'vests_per_year_override',
            'cliff_months_override', 'vesting_years_override', 'first_vest_date',
            'income_events', 'actuals', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'actuals', 'created_at', 'updated_at']

    def validate_bonus_extras(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('bonus_extras must be a list.')
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('Each extra bonus must be an object.')
            try:
                float(item.get('amount', 0))
            except (TypeError, ValueError):
                raise serializers.ValidationError('Extra bonus amount must be a number.')
        return value

    def validate_bonus_payouts(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('bonus_payouts must be a list.')
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('Each bonus payout must be an object.')
            try:
                percent = float(item.get('percent', 0))
            except (TypeError, ValueError):
                raise serializers.ValidationError('Bonus payout percent must be a number.')
            if percent < 0 or percent > 100:
                raise serializers.ValidationError('Bonus payout percent must be between 0 and 100.')
        return value

    def validate_period_deductions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('period_deductions must be a list.')
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('Each override must be an object.')
            try:
                period_index = int(item.get('periodIndex'))
            except (TypeError, ValueError):
                raise serializers.ValidationError('Each override needs a numeric periodIndex.')
            if period_index < 1:
                raise serializers.ValidationError('periodIndex is 1-based.')
        return value

    def validate_match_tiers(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('match_tiers must be a list.')
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('Each match tier must be an object.')
            try:
                float(item.get('matchPercent', 0))
                float(item.get('uptoPercent', 0))
            except (TypeError, ValueError):
                raise serializers.ValidationError('Match tier percents must be numbers.')
        return value

    def validate_allowances(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('allowances must be a list.')
        allowed = {'TAXABLE', 'TAX_FREE'}
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('Each allowance must be an object.')
            if item.get('treatment') not in allowed:
                raise serializers.ValidationError('Allowance treatment must be TAXABLE or TAX_FREE.')
            if item.get('payOn') not in {'FIRST', 'LAST'}:
                raise serializers.ValidationError('Allowance payOn must be FIRST or LAST.')
            if item.get('unit') not in {'PAYCHECK', 'MONTH', 'YEAR'}:
                raise serializers.ValidationError('Allowance unit must be PAYCHECK, MONTH or YEAR.')
            try:
                float(item.get('timesPer', 1))
            except (TypeError, ValueError):
                raise serializers.ValidationError('Allowance timesPer must be a number.')
        return value

    def validate_custom_deductions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('custom_deductions must be a list.')
        allowed = {'SECTION_125', 'PRETAX_INCOME_ONLY', 'POST_TAX'}
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('Each deduction must be an object.')
            if item.get('treatment') not in allowed:
                raise serializers.ValidationError(
                    'Deduction treatment must be SECTION_125, PRETAX_INCOME_ONLY or POST_TAX.'
                )
        return value

    def validate_income_events(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('income_events must be a list.')
        for event in value:
            if not isinstance(event, dict):
                raise serializers.ValidationError('Each income event must be an object.')
            if event.get('kind') not in {'bonus', 'vest', 'other'}:
                raise serializers.ValidationError("Event kind must be bonus, vest or other.")
        return value
