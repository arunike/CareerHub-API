from django.test import SimpleTestCase

from .management.commands.sync_tax_tables import build_tables, declared_years, diff_tables


def _policy(years, exemption=None):
    """A minimal stand-in for the source's sparse, year-indexed shape."""
    mars = ['single', 'mjoint', 'mseparate', 'headhh']
    policy = {
        'STD': {'value': [
            {'year': year, 'MARS': status, 'value': 10000 + year}
            for year in years for status in mars
        ]},
        # Rates are declared once and hold, which is why they are forward-filled.
        'FICA_ss_trt_employee': {'value': [{'year': 2013, 'value': 0.062}]},
        'FICA_mc_trt_employee': {'value': [{'year': 2013, 'value': 0.0145}]},
        'SS_Earnings_c': {'value': [{'year': year, 'value': 100000 + year} for year in years]},
    }
    if exemption is not None:
        policy['II_em'] = {'value': [{'year': year, 'value': exemption} for year in years]}
        policy['II_em_ps'] = {'value': [
            {'year': year, 'MARS': status, 'value': 250000} for year in years for status in mars
        ]}
        policy['II_em_po_step_size'] = {'value': [
            {'year': year, 'MARS': status, 'value': 2500} for year in years for status in mars
        ]}
        policy['II_em_prt'] = {'value': [{'year': 2013, 'value': 0.02}]}
    for index in range(1, 8):
        policy[f'II_rt{index}'] = {'value': [{'year': 2013, 'value': index / 100}]}
        policy[f'II_brk{index}'] = {'value': [
            {'year': year, 'MARS': status, 'value': 9e99 if index == 7 else index * 1000}
            for year in years for status in mars
        ]}
    return policy


class DeclaredYearsTests(SimpleTestCase):
    def test_reports_only_years_the_source_states(self):
        self.assertEqual(declared_years(_policy([2024, 2025])), {2024, 2025})

    def test_does_not_invent_a_year_beyond_the_source(self):
        built = build_tables(_policy([2024, 2025]), range(2024, 2030))
        self.assertEqual(sorted(built), ['2024', '2025'])

    def test_skips_a_year_before_the_source_begins(self):
        built = build_tables(_policy([2024]), range(2020, 2025))
        self.assertEqual(sorted(built), ['2024'])


class BuildTablesTests(SimpleTestCase):
    def setUp(self):
        self.built = build_tables(_policy([2025]), [2025])['2025']

    def test_covers_all_four_filing_statuses(self):
        self.assertEqual(
            sorted(self.built['brackets']),
            ['HEAD_OF_HOUSEHOLD', 'MARRIED_FILING_JOINTLY', 'MARRIED_FILING_SEPARATELY', 'SINGLE'],
        )

    def test_emits_seven_rates_per_status(self):
        for rows in self.built['brackets'].values():
            self.assertEqual(len(rows), 7)

    def test_marks_the_top_bracket_as_unbounded(self):
        # null travels through JSON, where Infinity cannot.
        self.assertIsNone(self.built['brackets']['SINGLE'][6]['cap'])

    def test_forward_fills_a_rate_declared_in_an_earlier_year(self):
        self.assertAlmostEqual(self.built['brackets']['SINGLE'][0]['rate'], 0.01)

    def test_carries_the_social_security_wage_base(self):
        social_security = self.built['payrollTaxes'][0]
        self.assertEqual(social_security['label'], 'Social Security')
        self.assertEqual(social_security['wageBase'], 102025)

    def test_leaves_medicare_uncapped(self):
        self.assertIsNone(self.built['payrollTaxes'][1]['wageBase'])

    def test_records_the_source_for_review(self):
        self.assertIn('Tax-Calculator', self.built['source'])


class DiffTablesTests(SimpleTestCase):
    def test_reports_nothing_when_unchanged(self):
        built = build_tables(_policy([2025]), [2025])
        self.assertEqual(diff_tables(built, built), [])

    def test_reports_an_added_year(self):
        built = build_tables(_policy([2025]), [2025])
        self.assertEqual(diff_tables({}, built), ['  + 2025 added'])

    def test_reports_a_changed_year(self):
        built = build_tables(_policy([2025]), [2025])
        stale = {'2025': {**built['2025'], 'supplementalRate': 0.25}}
        self.assertEqual(diff_tables(stale, built), ['  ~ 2025 changed'])

    def test_reports_a_dropped_year(self):
        built = build_tables(_policy([2025]), [2025])
        self.assertEqual(diff_tables({'2019': {}}, built), ['  - 2019 would be dropped', '  + 2025 added'])


class ExemptionTests(SimpleTestCase):
    def test_omits_exemption_fields_when_the_year_had_none(self):
        built = build_tables(_policy([2025], exemption=0), [2025])['2025']
        self.assertNotIn('personalExemption', built)

    def test_emits_exemption_fields_for_a_year_that_had_one(self):
        built = build_tables(_policy([2017], exemption=4050), [2017])['2017']
        self.assertEqual(built['personalExemption'], 4050)
        self.assertEqual(built['exemptionPhaseOutStart']['SINGLE'], 250000)
        self.assertEqual(built['exemptionPhaseOutStep']['SINGLE'], 2500)
        self.assertAlmostEqual(built['exemptionPhaseOutRate'], 0.02)

    def test_survives_a_source_without_the_exemption_parameters(self):
        # A restructured source should degrade to "no exemption", not abort the sync.
        built = build_tables(_policy([2025]), [2025])['2025']
        self.assertNotIn('personalExemption', built)
