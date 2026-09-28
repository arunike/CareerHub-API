import json
import os
import re
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand

from availability.models import CustomHoliday
from career.models import Application, Company, Contact, Experience, IncomeYear, Offer

REFERENCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))))),
    '.claude', 'reference', 'substitutes.json',
)

with open(REFERENCE, encoding='utf-8') as _handle:
    _REFERENCE = json.load(_handle)

# A fixture is allowed to use these, so the hook must never flag one.
SUBSTITUTES = {
    *_REFERENCE['companies'], *_REFERENCE['people'], *_REFERENCE['titles'],
    *_REFERENCE['locations'], *_REFERENCE['dates'].values(),
    *(str(v) for v in _REFERENCE['figures'].values() if isinstance(v, int)),
    *(str(v) for v in _REFERENCE['figures']['genericRoundAmounts']),
}

# Derived from this file, not the working directory, so the list cannot land outside CareerHub.
CAREERHUB = os.path.abspath(os.path.join(os.path.dirname(__file__), *['..'] * 5))

# Too common to match on: a bare small number appears in any file.
MIN_TEXT = 4
MIN_NUMBER = 1000
# Only a fixture or a doc has no honest reason to carry a premium-sized amount.
MIN_FIXTURE_NUMBER = 10

# A choice key is written in the code by construction, and a calendar year identifies nobody.
ENUM_SHAPED = re.compile(r"[A-Za-z][A-Za-z0-9]*(_[A-Za-z0-9]+)+")
CALENDAR_YEAR = re.compile(r"(19|20)\d\d")
NON_ZERO_CENTS = re.compile(r"-?\d+\.(?!00$)\d\d")

# Generic vocabulary: "Backend Engineer" identifies nobody, so these are not swept at all.
VOCABULARY_FIELDS = {
    'role_title', 'title', 'job_title', 'position', 'role', 'level', 'seniority',
    'work_arrangement', 'employment_type', 'work_mode',
}

# A name is an identifier; a note is prose the user typed. Everything else is weak evidence.
STRONG_FIELDS = {'name', 'email', 'notes', 'description', 'website', 'url', 'linkedin_url'}


class Command(BaseCommand):
    help = "Write the local leak-check denylist read by each repo's pre-commit hook. Values never printed."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--out",
            default=os.path.join(CAREERHUB, '.leakcheck', 'values.txt'),
            help="Defaults to CareerHub/.leakcheck/values.txt, which sits outside both git repos.",
        )

    def amount_of(self, value):
        if value in (None, '') or isinstance(value, bool):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def money(self, value):
        """A figure is worth blocking only above the noise floor, and in both its forms."""
        amount = self.amount_of(value)
        if amount is None or abs(amount) < MIN_NUMBER:
            return []
        forms = [f'{amount:.2f}']
        if amount == amount.to_integral():
            forms.append(str(int(amount)))
        return forms

    def cents_money(self, value):
        """A small amount is only distinguishable from ordinary code by its non-zero cents."""
        amount = self.amount_of(value)
        if amount is None or not MIN_FIXTURE_NUMBER <= abs(amount) < MIN_NUMBER:
            return []
        if amount == amount.quantize(Decimal('1')):
            return []
        return [f'{amount:.2f}']

    def strings_in(self, value):
        """Every label a JSON column holds, since an allowance or deduction name is personal too."""
        found = []
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in {'id', 'treatment', 'unit', 'payOn', 'kind'}:
                    continue
                found.extend(self.strings_in(inner))
        elif isinstance(value, list):
            for inner in value:
                found.extend(self.strings_in(inner))
        elif isinstance(value, str):
            found.extend(self.lines_of(value))
        elif isinstance(value, (int, float, Decimal)):
            found.extend(self.money(value))
        return found

    def small_money(self, queryset):
        """Premiums and per-paycheck deductions, which the main list drops as too common."""
        values = []
        for row in queryset:
            for field in row._meta.get_fields():
                if not hasattr(field, 'attname'):
                    continue
                kind = field.get_internal_type()
                value = getattr(row, field.attname, None)
                if value is None or isinstance(value, bool):
                    continue
                if kind in {'DecimalField', 'FloatField'}:
                    values.extend(self.cents_money(value))
                elif kind == 'JSONField':
                    values.extend(self.small_in(value))
        return values

    def small_in(self, value):
        """The same descent as strings_in, but keeping the small amounts instead of the labels."""
        found = []
        if isinstance(value, dict):
            for inner in value.values():
                found.extend(self.small_in(inner))
        elif isinstance(value, list):
            for inner in value:
                found.extend(self.small_in(inner))
        elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            found.extend(self.cents_money(value))
        return found

    def lines_of(self, value):
        return [line.strip() for line in str(value).splitlines() if line.strip()]

    def tier(self, value, strong):
        """Repo-wide only for a value with no honest reason to appear in any file."""
        if not value or value in SUBSTITUTES:
            return None
        if ENUM_SHAPED.fullmatch(value) or CALENDAR_YEAR.fullmatch(value):
            return None
        if len(value) < MIN_TEXT and not value.replace('.', '').lstrip('-').isdigit():
            return None
        if '@' in value or NON_ZERO_CENTS.fullmatch(value):
            return 'repo'
        # A one-word company name is an ordinary English word too, so it flags real code.
        if strong and ' ' in value:
            return 'repo'
        # A single word, a date and a round figure measured as noise even in fixtures.
        return None

    def sweep(self, queryset):
        """Read every text, money and date field rather than a hand-picked list."""
        skip = {'id', 'password', 'created_at', 'updated_at'}
        values = []
        strong_values = []
        for row in queryset:
            for field in row._meta.get_fields():
                if not hasattr(field, 'attname') or field.attname in skip:
                    continue
                if field.get_internal_type() in {'ForeignKey', 'OneToOneField', 'ManyToManyField'}:
                    continue
                if getattr(field, 'choices', None) or field.attname in VOCABULARY_FIELDS:
                    continue
                value = getattr(row, field.attname, None)
                if value is None or isinstance(value, bool):
                    continue
                kind = field.get_internal_type()
                strong = field.attname in STRONG_FIELDS or field.attname.endswith('_name')
                if kind in {'CharField', 'TextField', 'EmailField', 'URLField'}:
                    # A notes field spans lines, and each line has to be judged on its own.
                    (strong_values if strong else values).extend(self.lines_of(value))
                elif kind in {'DecimalField', 'IntegerField', 'FloatField', 'PositiveSmallIntegerField',
                              'PositiveIntegerField', 'SmallIntegerField', 'BigIntegerField'}:
                    values.extend(self.money(value))
                elif kind in {'DateField', 'DateTimeField'}:
                    values.append(value.isoformat()[:10])
                elif kind == 'JSONField':
                    values.extend(self.strings_in(value))
        return strong_values, values

    def handle(self, *args, **options):
        email = options["email"]
        values = set()
        strong = set()

        # Every model that can hold something the user typed, swept field by field.
        for queryset in (
            Company.objects.filter(user__email=email),
            Contact.objects.filter(user__email=email),
            CustomHoliday.objects.filter(user__email=email),
            Experience.objects.filter(user__email=email),
            Application.objects.filter(user__email=email),
            Offer.objects.filter(application__user__email=email),
            IncomeYear.objects.filter(user__email=email),
        ):
            from_names, from_rest = self.sweep(queryset)
            strong.update(from_names)
            values.update(from_rest)

        import datetime

        pay_counts = set()
        for year in IncomeYear.objects.filter(user__email=email):
            if year.paychecks_per_year_override:
                pay_counts.add(year.paychecks_per_year_override)
            if not year.first_pay_date:
                continue
            # The whole calendar, because a fixture borrows one date off it, not the anchor.
            step = 7 if year.paychecks_per_year_override == 52 else 14
            for index in range(30):
                values.add((year.first_pay_date + datetime.timedelta(days=step * index)).isoformat())

        # A per-period gross is derived, never stored, and is exactly what lands in a fixture.
        salaries = {o.base_salary for o in Offer.objects.filter(application__user__email=email)}
        salaries |= {r.base_salary for r in Experience.objects.filter(user__email=email)}
        for salary in salaries:
            if not salary:
                continue
            for count in pay_counts | {12, 24, 26, 27, 52}:
                values.update(self.money(Decimal(salary) / count))

        keep = sorted(v for v in values | strong if self.tier(v, v in strong) == 'repo')

        small = set()
        for queryset in (
            Offer.objects.filter(application__user__email=email),
            IncomeYear.objects.filter(user__email=email),
            Experience.objects.filter(user__email=email),
        ):
            small.update(self.small_money(queryset))

        # A per-period deferral is derived too, and it is the figure a pay-stub fixture quotes.
        percents = set()
        for year in IncomeYear.objects.filter(user__email=email):
            for step in (year.deferral_plan or {}).get('steps') or []:
                for key in ('pretaxPercent', 'rothPercent'):
                    amount = self.amount_of(step.get(key))
                    if amount:
                        percents.add(amount)
        for salary in salaries:
            if not salary:
                continue
            for count in pay_counts | {12, 24, 26, 27, 52}:
                per_period = Decimal(salary) / count
                for percent in percents:
                    small.update(self.cents_money(per_period * percent / 100))

        small_keep = sorted(v for v in small if v and v not in SUBSTITUTES)

        out = options["out"]
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(keep) + '\n')
        fixtures_out = os.path.join(os.path.dirname(out), 'values-fixtures.txt')
        with open(fixtures_out, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(small_keep) + '\n')
        self.stdout.write(self.style.SUCCESS(f'{len(keep)} values written to {out}'))
        self.stdout.write(self.style.SUCCESS(f'{len(small_keep)} small amounts written to {fixtures_out} (fixtures and docs only)'))
        self.stdout.write('Values are not printed here, and the path sits outside both git repos.')
