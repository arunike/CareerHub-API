from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import IncomeYear, PaycheckActual


class IncomeYearActualsAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="income-user@example.com",
            email="income-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def _create(self, actuals=None):
        payload = {'tax_year': 2026, 'source_key': 'experience-1'}
        if actuals is not None:
            payload['actuals'] = actuals
        return self.client.post('/api/career/income-years/', payload, format='json')

    def test_create_persists_recorded_paychecks(self):
        response = self._create(
            [
                {'period_index': 1, 'actual_net': '3380.56', 'note': 'First cheque'},
                {'period_index': 2, 'actual_net': '3346.87'},
            ]
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        year = IncomeYear.objects.get(user=self.user, tax_year=2026)
        self.assertEqual(year.actuals.count(), 2)
        first = year.actuals.get(period_index=1)
        self.assertEqual(first.actual_net, Decimal('3380.56'))
        self.assertEqual(first.note, 'First cheque')

    def test_read_returns_them_for_another_session(self):
        self._create([{'period_index': 1, 'actual_net': '3380.56'}])
        listed = self.client.get('/api/career/income-years/')
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(len(listed.data[0]['actuals']), 1)
        self.assertEqual(listed.data[0]['actuals'][0]['period_index'], 1)

    def test_update_replaces_the_set_and_drops_cleared_rows(self):
        created = self._create(
            [
                {'period_index': 1, 'actual_net': '3380.56'},
                {'period_index': 2, 'actual_net': '3346.87'},
            ]
        )
        record_id = created.data['id']

        response = self.client.patch(
            f'/api/career/income-years/{record_id}/',
            {'actuals': [{'period_index': 2, 'actual_net': '9999.00'}]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        year = IncomeYear.objects.get(pk=record_id)
        self.assertEqual([row.period_index for row in year.actuals.all()], [2])
        self.assertEqual(year.actuals.get(period_index=2).actual_net, Decimal('9999.00'))

    def test_update_without_the_key_leaves_recorded_paychecks_alone(self):
        created = self._create([{'period_index': 1, 'actual_net': '3380.56'}])
        self.client.patch(
            f'/api/career/income-years/{created.data["id"]}/',
            {'pretax_401k_percent': '6'},
            format='json',
        )
        self.assertEqual(PaycheckActual.objects.filter(income_year=created.data['id']).count(), 1)

    def test_pay_date_override_survives_the_round_trip(self):
        created = self._create(
            [{'period_index': 3, 'pay_date': '2026-01-30', 'actual_net': '3358.05'}]
        )
        fetched = self.client.get(f'/api/career/income-years/{created.data["id"]}/')
        self.assertEqual(fetched.data['actuals'][0]['pay_date'], '2026-01-30')

    def test_off_cycle_period_index_is_accepted(self):
        # Off-cycle bonus payments are numbered from OFF_CYCLE_BASE = 1000 on the client.
        response = self._create([{'period_index': 1007, 'actual_net': '20328.16'}])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['actuals'][0]['period_index'] == 1007)

    def test_duplicate_pay_period_is_rejected(self):
        response = self._create(
            [
                {'period_index': 1, 'actual_net': '1.00'},
                {'period_index': 1, 'actual_net': '2.00'},
            ]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_another_user_cannot_see_recorded_paychecks(self):
        self._create([{'period_index': 1, 'actual_net': '3380.56'}])
        other = get_user_model().objects.create_user(
            username="other-user@example.com",
            email="other-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get('/api/career/income-years/').data, [])


class IncomeYearAllowanceAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="allowance-user@example.com",
            email="allowance-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def _create(self, allowances):
        return self.client.post(
            '/api/career/income-years/',
            {'tax_year': 2026, 'source_key': 'experience-1', 'allowances': allowances},
            format='json',
        )

    def _once(self, **overrides):
        allowance = {
            'id': 'allowance-1',
            'label': 'Referral bonus',
            'amount': 1500,
            'treatment': 'TAXABLE',
            'timesPer': 1,
            'unit': 'ONCE',
            'payOn': 'FIRST',
            'payPeriodIndex': 7,
        }
        allowance.update(overrides)
        return allowance

    def test_one_time_allowance_round_trips_to_another_session(self):
        self.assertEqual(self._create([self._once()]).status_code, status.HTTP_201_CREATED)

        listed = self.client.get('/api/career/income-years/')
        stored = listed.data[0]['allowances'][0]
        self.assertEqual(stored['unit'], 'ONCE')
        self.assertEqual(stored['payPeriodIndex'], 7)
        self.assertEqual(stored['label'], 'Referral bonus')

    def test_a_one_time_allowance_may_name_no_paycheck(self):
        response = self._create([self._once(payPeriodIndex=None)])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['allowances'][0]['payPeriodIndex'])

    def test_recurring_units_still_save(self):
        for unit in ('PAYCHECK', 'MONTH', 'YEAR'):
            IncomeYear.objects.filter(user=self.user).delete()
            response = self._create([self._once(unit=unit, payPeriodIndex=None)])
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, unit)

    def test_an_unknown_unit_is_still_rejected(self):
        response = self._create([self._once(unit='FORTNIGHT')])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_non_numeric_pay_period_index_is_rejected(self):
        response = self._create([self._once(payPeriodIndex='seventh')])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class IncomeYearDeferralBaseAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="deferral-user@example.com",
            email="deferral-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def _create(self, **extra):
        payload = {'tax_year': 2026, 'source_key': 'experience-1'}
        payload.update(extra)
        return self.client.post('/api/career/income-years/', payload, format='json')

    def test_defaults_to_all_pay(self):
        self.assertEqual(self._create().status_code, status.HTTP_201_CREATED)
        self.assertEqual(IncomeYear.objects.get(user=self.user).deferral_base, 'ALL')

    def test_each_base_round_trips(self):
        for base in ('ALL', 'NO_ALLOWANCES', 'SALARY_ONLY'):
            IncomeYear.objects.filter(user=self.user).delete()
            self.assertEqual(
                self._create(deferral_base=base).status_code, status.HTTP_201_CREATED, base
            )
            listed = self.client.get('/api/career/income-years/')
            self.assertEqual(listed.data[0]['deferral_base'], base)

    def test_an_unknown_base_is_rejected(self):
        response = self._create(deferral_base='BASE_PAY')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
