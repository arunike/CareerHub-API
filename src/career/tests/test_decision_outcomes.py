from datetime import date

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, Company, Offer, OfferDecisionJournal
from ..services.decision_outcomes import MINIMUM_DECISIONS_FOR_PATTERN

URL = '/api/career/decision-outcome-insights/'


class DecisionOutcomeInsightsTests(APITestCase):
    """Comparing what was expected against what the 30/90 day look-backs recorded."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="outcomes@example.com",
            email="outcomes@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.company = Company.objects.create(user=self.user, name="Google")

    def _journal(self, **overrides):
        application = Application.objects.create(
            user=self.user,
            company=overrides.pop('company', self.company),
            role_title="Software Engineer",
            status='OFFER',
        )
        offer = Offer.objects.create(application=application, base_salary=165000)
        return OfferDecisionJournal.objects.create(
            offer=offer,
            decision=overrides.pop('decision', 'ACCEPTED'),
            decided_on=overrides.pop('decided_on', date(2026, 7, 1)),
            **overrides,
        )

    def _criteria(self, response):
        return {row['key']: row for row in response.data['criteria']}

    def test_lists_the_concerns_that_turned_out_real(self):
        self._journal(
            concerns=[
                {'id': 'c1', 'text': 'The on-call rotation is thin', 'outcome': 'REAL'},
                {'id': 'c2', 'text': 'The commute may be long', 'outcome': 'AVOIDED'},
            ]
        )
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        became_real = response.data['concerns_became_real']
        self.assertEqual(len(became_real), 1)
        self.assertEqual(became_real[0]['text'], 'The on-call rotation is thin')
        self.assertEqual(became_real[0]['company_name'], 'Google')

    def test_counts_the_concerns_still_waiting_on_a_look_back(self):
        self._journal(
            concerns=[
                {'id': 'c1', 'text': 'Thin on-call', 'outcome': 'REAL'},
                {'id': 'c2', 'text': 'Long commute', 'outcome': None},
                {'id': 'c3', 'text': 'Unclear scope', 'outcome': 'UNCLEAR'},
            ]
        )
        response = self.client.get(URL)
        self.assertEqual(response.data['concerns_raised'], 3)
        # UNCLEAR is not a resolution: it says the look-back could not tell yet.
        self.assertEqual(response.data['concerns_resolved'], 1)

    def test_reports_which_criteria_drove_the_calls(self):
        self._journal(criteria=['financial', 'trajectory'])
        self._journal(criteria=['financial'])
        rows = self._criteria(self.client.get(URL))
        self.assertEqual(rows['financial']['chosen_count'], 2)
        self.assertEqual(rows['trajectory']['chosen_count'], 1)

    def test_the_most_used_criterion_is_reported_first(self):
        self._journal(criteria=['brand'])
        self._journal(criteria=['financial'])
        self._journal(criteria=['financial'])
        self.assertEqual(self.client.get(URL).data['criteria'][0]['key'], 'financial')

    def test_counts_how_each_criterion_actually_turned_out(self):
        self._journal(
            criteria=['financial'],
            reviews=[
                {
                    'milestone': 30,
                    'completed_on': '2026-10-01',
                    'criteria_verdicts': {'financial': 'WORSE'},
                }
            ],
        )
        rows = self._criteria(self.client.get(URL))
        self.assertEqual(rows['financial']['worse'], 1)
        self.assertEqual(rows['financial']['judged_count'], 1)

    def test_the_ninety_day_view_supersedes_the_thirty_day_one(self):
        self._journal(
            criteria=['trajectory'],
            reviews=[
                {
                    'milestone': 30,
                    'completed_on': '2026-08-01',
                    'criteria_verdicts': {'trajectory': 'AS_EXPECTED'},
                },
                {
                    'milestone': 90,
                    'completed_on': '2026-10-01',
                    'criteria_verdicts': {'trajectory': 'WORSE'},
                },
            ],
        )
        rows = self._criteria(self.client.get(URL))
        self.assertEqual(rows['trajectory']['worse'], 1)
        self.assertEqual(rows['trajectory']['as_expected'], 0)
        self.assertEqual(rows['trajectory']['judged_count'], 1)

    def test_an_unfinished_look_back_is_not_treated_as_evidence(self):
        self._journal(
            criteria=['brand'],
            reviews=[{'milestone': 30, 'criteria_verdicts': {'brand': 'WORSE'}}],
        )
        rows = self._criteria(self.client.get(URL))
        self.assertEqual(rows['brand']['judged_count'], 0)
        self.assertEqual(self.client.get(URL).data['reviewed_count'], 0)

    def test_flags_a_criterion_with_too_little_behind_it_to_be_a_pattern(self):
        self._journal(
            criteria=['location'],
            reviews=[
                {
                    'milestone': 30,
                    'completed_on': '2026-10-01',
                    'criteria_verdicts': {'location': 'WORSE'},
                }
            ],
        )
        self.assertTrue(self._criteria(self.client.get(URL))['location']['below_minimum_sample'])

    def test_clears_the_flag_once_enough_decisions_have_been_judged(self):
        for _ in range(MINIMUM_DECISIONS_FOR_PATTERN):
            self._journal(
                criteria=['location'],
                reviews=[
                    {
                        'milestone': 30,
                        'completed_on': '2026-10-01',
                        'criteria_verdicts': {'location': 'WORSE'},
                    }
                ],
            )
        row = self._criteria(self.client.get(URL))['location']
        self.assertEqual(row['worse'], MINIMUM_DECISIONS_FOR_PATTERN)
        self.assertFalse(row['below_minimum_sample'])

    def test_ignores_a_criterion_key_that_is_not_one_of_the_scorecard_categories(self):
        journal = self._journal()
        OfferDecisionJournal.objects.filter(pk=journal.pk).update(
            criteria=['made_up'],
            reviews=[
                {
                    'milestone': 30,
                    'completed_on': '2026-10-01',
                    'criteria_verdicts': {'made_up': 'WORSE'},
                }
            ],
        )
        self.assertEqual(self.client.get(URL).data['criteria'], [])

    def test_survives_a_journal_whose_json_is_not_the_expected_shape(self):
        journal = self._journal()
        OfferDecisionJournal.objects.filter(pk=journal.pk).update(
            concerns=['just a string'], reviews=[{'milestone': 30, 'completed_on': '2026-10-01'}]
        )
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['concerns_raised'], 0)

    def test_counts_the_decisions_and_how_many_have_been_looked_back_on(self):
        self._journal()
        self._journal(
            reviews=[{'milestone': 30, 'completed_on': '2026-10-01', 'verdict': 'HELD_UP'}]
        )
        response = self.client.get(URL)
        self.assertEqual(response.data['journal_count'], 2)
        self.assertEqual(response.data['reviewed_count'], 1)

    def test_says_nothing_about_another_users_decisions(self):
        stranger = get_user_model().objects.create_user(
            username="stranger-outcomes@example.com",
            email="stranger-outcomes@example.com",
            password="StrongPassw0rd!",
        )
        their_company = Company.objects.create(user=stranger, name="Netflix")
        their_application = Application.objects.create(
            user=stranger, company=their_company, role_title="Software Engineer II", status='OFFER'
        )
        OfferDecisionJournal.objects.create(
            offer=Offer.objects.create(application=their_application, base_salary=336000),
            decision='ACCEPTED',
            decided_on=date(2026, 7, 1),
            concerns=[{'id': 'c1', 'text': 'Theirs', 'outcome': 'REAL'}],
        )
        self._journal()
        response = self.client.get(URL)
        self.assertEqual(response.data['journal_count'], 1)
        self.assertEqual(response.data['concerns_became_real'], [])

    def test_an_account_with_no_journals_reports_zeroes(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['journal_count'], 0)
        self.assertEqual(response.data['criteria'], [])

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED)


class DecisionJournalOutcomeValidationTests(APITestCase):
    """The journal endpoint has to refuse a shape the insights cannot read."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="journal-validation@example.com",
            email="journal-validation@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        company = Company.objects.create(user=self.user, name="Google")
        application = Application.objects.create(
            user=self.user, company=company, role_title="Software Engineer", status='OFFER'
        )
        self.offer = Offer.objects.create(application=application, base_salary=165000)

    def _post(self, **overrides):
        payload = {
            'offer': self.offer.id,
            'decision': 'ACCEPTED',
            'decided_on': '2026-07-01',
            'concerns': [],
            'criteria': [],
            'reviews': [],
        }
        payload.update(overrides)
        return self.client.post('/api/career/offer-decision-journal/', payload, format='json')

    def test_accepts_itemised_concerns_and_criteria(self):
        response = self._post(
            concerns=[{'id': 'c1', 'text': 'Thin on-call', 'outcome': None}],
            criteria=['financial', 'trajectory'],
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['criteria'], ['financial', 'trajectory'])

    def test_rejects_a_concern_with_no_id_to_mark_later(self):
        self.assertEqual(
            self._post(concerns=[{'text': 'Thin on-call'}]).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_rejects_two_concerns_sharing_an_id(self):
        response = self._post(
            concerns=[{'id': 'c1', 'text': 'One'}, {'id': 'c1', 'text': 'Two'}]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_an_outcome_that_is_not_one_of_the_three(self):
        response = self._post(concerns=[{'id': 'c1', 'text': 'One', 'outcome': 'MAYBE'}])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_a_criterion_outside_the_scorecard_categories(self):
        self.assertEqual(self._post(criteria=['vibes']).status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_the_same_criterion_twice(self):
        response = self._post(criteria=['financial', 'financial'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_an_unknown_criterion_verdict_in_a_review(self):
        response = self._post(
            reviews=[{'milestone': 30, 'criteria_verdicts': {'financial': 'GREAT'}}]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reads_the_criteria_verdicts_back_through_a_second_request(self):
        created = self._post(
            criteria=['financial'],
            reviews=[
                {
                    'milestone': 30,
                    'completed_on': '2026-10-01',
                    'criteria_verdicts': {'financial': 'WORSE'},
                }
            ],
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        listed = self.client.get('/api/career/offer-decision-journal/')
        self.assertEqual(listed.data[0]['reviews'][0]['criteria_verdicts'], {'financial': 'WORSE'})
