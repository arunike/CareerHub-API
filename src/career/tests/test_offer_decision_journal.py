from datetime import date

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, Company, Offer, OfferDecisionJournal


class OfferDecisionJournalTests(APITestCase):
    """Recording why an offer was taken, and reviewing that call 30 and 90 days later."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="journal@example.com",
            email="journal@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.company = Company.objects.create(user=self.user, name="Google")
        self.offer = self._offer(self.user, self.company)

    def _offer(self, user, company, role_title="Software Engineer"):
        application = Application.objects.create(
            user=user,
            company=company,
            role_title=role_title,
            status='OFFER',
        )
        return Offer.objects.create(application=application, base_salary=165000)

    def _payload(self, **overrides):
        payload = {
            'offer': self.offer.id,
            'decision': 'ACCEPTED',
            'decided_on': '2026-07-01',
            'started_on': '2026-10-01',
            'reasons': 'The team owns the product end to end.',
            'concerns': [{'id': 'c1', 'text': 'The on-call rotation is thin.', 'outcome': None}],
            'reviews': [],
        }
        payload.update(overrides)
        return payload

    def test_creates_a_journal_and_reports_the_company_and_role(self):
        response = self.client.post(
            '/api/career/offer-decision-journal/', self._payload(), format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['company_name'], 'Google')
        self.assertEqual(response.data['role_title'], 'Software Engineer')

    def test_records_a_look_back_against_a_milestone(self):
        created = self.client.post(
            '/api/career/offer-decision-journal/', self._payload(), format='json'
        )
        reviews = [
            {
                'milestone': 30,
                'completed_on': '2026-11-01',
                'verdict': 'HELD_UP',
                'notes': 'The ownership was real.',
            }
        ]
        response = self.client.patch(
            f"/api/career/offer-decision-journal/{created.data['id']}/",
            {'reviews': reviews},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['reviews'][0]['verdict'], 'HELD_UP')

    def test_rejects_a_review_without_a_milestone(self):
        response = self.client.post(
            '/api/career/offer-decision-journal/',
            self._payload(reviews=[{'verdict': 'MIXED'}]),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('reviews', response.data)

    def test_rejects_a_review_list_that_is_not_a_list(self):
        response = self.client.post(
            '/api/career/offer-decision-journal/',
            self._payload(reviews={'milestone': 30}),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_declined_offer_needs_no_start_date(self):
        response = self.client.post(
            '/api/career/offer-decision-journal/',
            self._payload(decision='DECLINED', started_on=None),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['started_on'])

    def test_one_journal_per_offer(self):
        self.client.post('/api/career/offer-decision-journal/', self._payload(), format='json')
        second = self.client.post(
            '/api/career/offer-decision-journal/', self._payload(), format='json'
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_journal_someone_elses_offer(self):
        stranger = get_user_model().objects.create_user(
            username="stranger@example.com",
            email="stranger@example.com",
            password="StrongPassw0rd!",
        )
        their_company = Company.objects.create(user=stranger, name="Netflix")
        their_offer = self._offer(stranger, their_company, role_title="Software Engineer II")
        response = self.client.post(
            '/api/career/offer-decision-journal/',
            self._payload(offer=their_offer.id),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_list_only_shows_your_own_journals(self):
        stranger = get_user_model().objects.create_user(
            username="stranger2@example.com",
            email="stranger2@example.com",
            password="StrongPassw0rd!",
        )
        their_company = Company.objects.create(user=stranger, name="Netflix")
        OfferDecisionJournal.objects.create(
            offer=self._offer(stranger, their_company, role_title="Software Engineer II"),
            decision='DECLINED',
            decided_on=date(2026, 7, 1),
        )
        OfferDecisionJournal.objects.create(
            offer=self.offer, decision='ACCEPTED', decided_on=date(2026, 7, 1)
        )
        response = self.client.get('/api/career/offer-decision-journal/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['company_name'], 'Google')

    def test_review_anchor_prefers_the_start_date(self):
        journal = OfferDecisionJournal.objects.create(
            offer=self.offer,
            decision='ACCEPTED',
            decided_on=date(2026, 7, 1),
            started_on=date(2026, 10, 1),
        )
        self.assertEqual(journal.review_anchor, date(2026, 10, 1))
        journal.started_on = None
        self.assertEqual(journal.review_anchor, date(2026, 7, 1))

    def test_a_journal_can_be_deleted_again(self):
        created = self.client.post(
            '/api/career/offer-decision-journal/', self._payload(), format='json'
        )
        response = self.client.delete(
            f"/api/career/offer-decision-journal/{created.data['id']}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get('/api/career/offer-decision-journal/').data, [])

    def test_cannot_delete_someone_elses_journal(self):
        stranger = get_user_model().objects.create_user(
            username="stranger-delete@example.com",
            email="stranger-delete@example.com",
            password="StrongPassw0rd!",
        )
        their_company = Company.objects.create(user=stranger, name="Netflix")
        their_journal = OfferDecisionJournal.objects.create(
            offer=self._offer(stranger, their_company, role_title="Software Engineer II"),
            decision='ACCEPTED',
            decided_on=date(2026, 7, 1),
        )
        response = self.client.delete(
            f'/api/career/offer-decision-journal/{their_journal.id}/'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(OfferDecisionJournal.objects.filter(pk=their_journal.pk).exists())
