import json
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand

SOURCE_URL = (
    'https://raw.githubusercontent.com/PSLmodels/Tax-Calculator/master/taxcalc/'
    'policy_current_law.json'
)

OUTPUT_PATH = Path(__file__).resolve().parents[2] / 'data' / 'federal_tax_tables.json'

FRONTEND_PATH = (
    Path(__file__).resolve().parents[5]
    / 'frontend'
    / 'src'
    / 'pages'
    / 'Income'
    / 'tax'
    / 'data'
    / 'federal-generated.json'
)

# The source begins in 2013. Earlier years are not published anywhere machine-readable.
MIN_MODELLED_YEAR = 2013

FILING_STATUS = {
    'single': 'SINGLE',
    'mjoint': 'MARRIED_FILING_JOINTLY',
    'mseparate': 'MARRIED_FILING_SEPARATELY',
    'headhh': 'HEAD_OF_HOUSEHOLD',
}

RATE_PARAMS = [f'II_rt{index}' for index in range(1, 8)]
BRACKET_PARAMS = [f'II_brk{index}' for index in range(1, 8)]

# Anything at or above this is the source's stand-in for "no upper bound".
UNBOUNDED = 8e99


def _param(policy, name):
    return policy.get(name, {}).get('value', [])


def _latest_at(values, year, mars=None):
    """Sparse: a year's value holds until it is changed."""
    candidates = [
        entry
        for entry in values
        if entry.get('year', 0) <= year and (mars is None or entry.get('MARS') == mars)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda entry: entry['year'])['value']


def declared_years(policy):
    """Stated years only; forward-filling would invent 2027 out of 2026's figures."""
    sets = [
        {entry['year'] for entry in policy[param]['value']}
        for param in ['STD', *BRACKET_PARAMS]
    ]
    return set.intersection(*sets) if sets else set()


def build_tables(policy, years):
    tables = {}
    available = declared_years(policy)
    for year in years:
        if year not in available:
            continue
        brackets = {}
        for mars, status in FILING_STATUS.items():
            rows = []
            for rate_param, bracket_param in zip(RATE_PARAMS, BRACKET_PARAMS):
                rate = _latest_at(policy[rate_param]['value'], year)
                cap = _latest_at(policy[bracket_param]['value'], year, mars)
                if rate is None or cap is None:
                    rows = []
                    break
                # null means unbounded; the client reads it as Infinity.
                rows.append({'cap': None if cap >= UNBOUNDED else cap, 'rate': rate})
            if not rows:
                break
            brackets[status] = rows

        if len(brackets) != len(FILING_STATUS):
            continue

        deduction = {
            status: _latest_at(policy['STD']['value'], year, mars)
            for mars, status in FILING_STATUS.items()
        }
        if any(value is None for value in deduction.values()):
            continue

        # Pre-2018 personal exemption, with its phase-out.
        exemption = _latest_at(_param(policy, 'II_em'), year) or 0
        phase_out_start = {
            status: _latest_at(_param(policy, 'II_em_ps'), year, mars)
            for mars, status in FILING_STATUS.items()
        }
        phase_out_step = {
            status: _latest_at(_param(policy, 'II_em_po_step_size'), year, mars)
            for mars, status in FILING_STATUS.items()
        }
        phase_out_rate = _latest_at(_param(policy, 'II_em_prt'), year)

        wage_base = _latest_at(_param(policy, 'SS_Earnings_c'), year)
        ss_rate = _latest_at(_param(policy, 'FICA_ss_trt_employee'), year)
        mc_rate = _latest_at(_param(policy, 'FICA_mc_trt_employee'), year)

        tables[str(year)] = {
            'year': year,
            'jurisdiction': 'federal',
            'tier': 'full',
            'source': f'PSLmodels Tax-Calculator policy_current_law.json ({year})',
            'standardDeduction': deduction,
            'brackets': brackets,
            **(
                {
                    'personalExemption': exemption,
                    'exemptionPhaseOutStart': phase_out_start,
                    'exemptionPhaseOutStep': phase_out_step,
                    'exemptionPhaseOutRate': phase_out_rate,
                }
                if exemption
                else {}
            ),
            'supplementalRate': 0.22,
            'supplementalHighRate': 0.37,
            'supplementalHighThreshold': 1000000,
            'payrollTaxes': [
                {
                    'label': 'Social Security',
                    'rate': ss_rate,
                    'wageBase': wage_base,
                    'appliesAbove': None,
                },
                {'label': 'Medicare', 'rate': mc_rate, 'wageBase': None, 'appliesAbove': None},
                {
                    'label': 'Additional Medicare',
                    'rate': 0.009,
                    'wageBase': None,
                    'appliesAbove': 200000,
                },
            ],
        }
    return tables


def diff_tables(existing, built):
    changes = []
    for year in sorted(set(existing) | set(built)):
        before, after = existing.get(year), built.get(year)
        if before is None:
            changes.append(f'  + {year} added')
        elif after is None:
            changes.append(f'  - {year} would be dropped')
        elif before != after:
            changes.append(f'  ~ {year} changed')
    return changes


class Command(BaseCommand):
    help = 'Sync federal tax tables from Tax-Calculator into the served registry.'

    def add_arguments(self, parser):
        parser.add_argument('--write', action='store_true', help='Persist the rebuilt tables.')
        parser.add_argument('--from-year', type=int, default=MIN_MODELLED_YEAR)
        parser.add_argument(
            '--frontend-out',
            action='store_true',
            help='Also write the bundle the frontend imports, for years the API cannot reach.',
        )
        parser.add_argument('--to-year', type=int, default=2030)
        parser.add_argument('--url', default=SOURCE_URL)

    def handle(self, *args, **options):
        self.stdout.write(f'Fetching {options["url"]}')
        with urllib.request.urlopen(options['url'], timeout=60) as response:
            policy = json.loads(response.read().decode('utf-8'))

        from_year = max(options['from_year'], MIN_MODELLED_YEAR)
        if options['from_year'] < MIN_MODELLED_YEAR:
            self.stdout.write(
                self.style.WARNING(
                    f'Ignoring years before {MIN_MODELLED_YEAR}: the source does not publish them.'
                )
            )
        years = range(from_year, options['to_year'] + 1)
        built = build_tables(policy, years)
        self.stdout.write(f'Built {len(built)} years: {", ".join(sorted(built))}')

        existing = {}
        if OUTPUT_PATH.exists():
            existing = json.loads(OUTPUT_PATH.read_text())

        changes = diff_tables(existing, built)
        if not changes:
            self.stdout.write(self.style.SUCCESS('No changes.'))
            return

        self.stdout.write('Changes:')
        for line in changes:
            self.stdout.write(line)

        if not options['write']:
            self.stdout.write(self.style.WARNING('Dry run. Re-run with --write to persist.'))
            return

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(built, indent=2, sort_keys=True) + '\n')
        self.stdout.write(self.style.SUCCESS(f'Wrote {OUTPUT_PATH}'))

        if options['frontend_out'] and FRONTEND_PATH.parent.exists():
            FRONTEND_PATH.write_text(json.dumps(built, indent=2, sort_keys=True) + '\n')
            self.stdout.write(self.style.SUCCESS(f'Wrote {FRONTEND_PATH}'))
