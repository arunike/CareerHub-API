import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, Company, Experience, Offer
from ..services.offers import calculate_realizable_equity


class OfferLinkedExperienceSerializerTests(APITestCase):
    """The offers page Past Experience filter reads this field."""
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="linked-exp@example.com",
            email="linked-exp@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.company = Company.objects.create(user=self.user, name="Google")

    def _offer(self, role_title, base=100000):
        application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title=role_title,
            status='OFFER',
        )
        return Offer.objects.create(application=application, base_salary=base)

    def test_offer_without_experience_reports_none(self):
        self._offer("Software Engineer")
        response = self.client.get('/api/career/offers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data[0]['linked_experience'])

    def test_offer_with_experience_reports_the_flag_and_dates(self):
        offer = self._offer("Software Engineer")
        Experience.objects.create(
            user=self.user,
            offer=offer,
            title="Software Engineer",
            company="Google",
            start_date=date(2025, 1, 6),
            end_date=date(2026, 8, 14),
            is_current=False,
        )
        response = self.client.get('/api/career/offers/')
        linked = response.data[0]['linked_experience']
        self.assertEqual(linked['title'], "Software Engineer")
        self.assertEqual(linked['company'], "Google")
        self.assertEqual(str(linked['start_date']), '2025-01-06')
        self.assertEqual(str(linked['end_date']), '2026-08-14')
        self.assertFalse(linked['is_current'])

    def test_most_recent_experience_wins(self):
        offer = self._offer("Software Engineer")
        Experience.objects.create(
            user=self.user, offer=offer, title="Intern", company="Google",
            start_date=date(2024, 6, 1), end_date=date(2024, 8, 30), is_current=False,
        )
        Experience.objects.create(
            user=self.user, offer=offer, title="Software Engineer", company="Google",
            start_date=date(2025, 1, 6), end_date=None, is_current=True,
        )
        response = self.client.get('/api/career/offers/')
        self.assertEqual(response.data[0]['linked_experience']['title'], "Software Engineer")

    def test_experience_without_start_date_does_not_crash(self):
        offer = self._offer("Software Engineer")
        Experience.objects.create(
            user=self.user, offer=offer, title="Undated", company="Google",
            start_date=None, end_date=None, is_current=False,
        )
        Experience.objects.create(
            user=self.user, offer=offer, title="Also Undated", company="Google",
            start_date=None, end_date=None, is_current=False,
        )
        response = self.client.get('/api/career/offers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data[0]['linked_experience'])


class OfferDecisionSnapshotAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="snapshot-user@example.com",
            email="snapshot-user@example.com",
            password="StrongPassw0rd!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-snapshot-user@example.com",
            email="other-snapshot-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        company = Company.objects.create(user=self.user, name="Google")
        application = Application.objects.create(
            user=self.user,
            company=company,
            role_title="Backend Engineer",
            status="OFFER",
            location="San Francisco, CA",
            office_location="San Francisco, CA",
            rto_policy="HYBRID",
            rto_days_per_week=3,
            commute_cost_value=20,
            commute_cost_frequency="DAILY",
            tax_base_rate=32,
            monthly_rent_override=3500,
        )
        self.offer = Offer.objects.create(
            application=application,
            base_salary=180000,
            bonus=25000,
            equity=60000,
            sign_on=30000,
            benefits_value=12000,
            pto_days=20,
            holiday_days=11,
        )
        other_company = Company.objects.create(user=self.other_user, name="Netflix")
        other_application = Application.objects.create(
            user=self.other_user,
            company=other_company,
            role_title="Hidden Engineer",
            status="OFFER",
        )
        self.other_offer = Offer.objects.create(
            application=other_application,
            base_salary=1,
            bonus=0,
            equity=0,
            sign_on=0,
            benefits_value=0,
            pto_days=10,
        )

    def _snapshot_payload(self, **overrides):
        payload = {
            "offer": self.offer.id,
            "title": "Decision before onsite counter",
            "notes": "Leaning Google because adjusted value and team score are strong.",
            "decision_score": 87,
            "rank": 1,
            "total_comp": "307000.00",
            "adjusted_value": "241500.50",
            "monthly_rent": "3500.00",
            "commute_cost_annual": "5200.00",
            "tax_snapshot": {
                "base": 32,
                "bonus": 40,
                "equity": 42,
            },
            "score_categories": [
                {"key": "financial", "label": "Financial", "score": 100, "weight": 44},
                {"key": "team", "label": "Team", "score": 80, "weight": 6},
            ],
            "offer_snapshot": {
                "base_salary": 180000,
                "bonus": 25000,
                "equity": 60000,
                "sign_on": 30000,
                "benefits_value": 12000,
                "company": "Google",
                "role": "Backend Engineer",
            },
            "adjustment_snapshot": {
                "marital_status": "SINGLE",
                "reference_location": "San Francisco, CA",
            },
        }
        payload.update(overrides)
        return payload

    def test_snapshots_are_created_listed_and_user_scoped(self):
        response = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["company_name"], "Google")
        self.assertEqual(response.data["role_title"], "Backend Engineer")

        forbidden = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(offer=self.other_offer.id),
            format="json",
        )
        self.assertEqual(forbidden.status_code, status.HTTP_400_BAD_REQUEST)

        list_response = self.client.get(
            "/api/career/offer-decision-snapshots/",
            {"offer": self.offer.id},
        )
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["decision_score"], 87)

    def test_snapshot_accepts_decision_score_above_financial_benchmark(self):
        response = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(
                decision_score=125,
                score_categories=[
                    {"key": "financial", "label": "Financial", "score": 156, "weight": 44},
                    {"key": "team", "label": "Team", "score": 80, "weight": 6},
                ],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["decision_score"], 125)
        self.assertEqual(response.data["score_categories"][0]["score"], 156)

    def test_locked_snapshots_are_preserved_from_delete_actions(self):
        locked = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(title="Locked", is_locked=True),
            format="json",
        ).data
        unlocked = self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(title="Unlocked"),
            format="json",
        ).data

        delete_locked = self.client.delete(f"/api/career/offer-decision-snapshots/{locked['id']}/")
        self.assertEqual(delete_locked.status_code, status.HTTP_403_FORBIDDEN)

        delete_all = self.client.delete("/api/career/offer-decision-snapshots/delete_all/")
        self.assertEqual(delete_all.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_all.data["deleted"], 1)

        remaining = self.client.get("/api/career/offer-decision-snapshots/").data
        self.assertEqual([item["id"] for item in remaining], [locked["id"]])
        self.assertFalse(any(item["id"] == unlocked["id"] for item in remaining))

    def test_account_export_and_restore_include_offer_decision_snapshots(self):
        self.client.post(
            "/api/career/offer-decision-snapshots/",
            self._snapshot_payload(is_locked=True),
            format="json",
        )

        export_response = self.client.get("/api/user-settings/account-export/", {"fmt": "json"})
        self.assertEqual(export_response.status_code, status.HTTP_200_OK)
        payload = json.loads(export_response.content.decode("utf-8"))
        snapshots = payload["career"]["offer_decision_snapshots"]
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["offer_company"], "Google")
        self.assertEqual(snapshots[0]["decision_score"], 87)

        backup_file = SimpleUploadedFile(
            "careerhub-account-export.json",
            json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )
        restore_response = self.client.post(
            "/api/user-settings/restore-backup/",
            {"file": backup_file, "mode": "replace"},
            format="multipart",
        )

        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        self.assertEqual(restore_response.data["created_counts"]["offer_decision_snapshots"], 1)
        restored = self.client.get("/api/career/offer-decision-snapshots/").data
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["title"], "Decision before onsite counter")
        self.assertTrue(restored[0]["is_locked"])


class FreeFoodPerMealTests(APITestCase):
    """Valued per meal over office days, not as a flat yearly guess."""
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="free-food@example.com",
            email="free-food@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.company = Company.objects.create(user=self.user, name='Google')

    def test_per_meal_entries_round_trip(self):
        """One object per meal, which is what the offer form sends."""
        application = Application.objects.create(
            user=self.user, company=self.company, role_title='Software Engineer', status='OFFER'
        )
        entries = [
            {'meal': 'BREAKFAST', 'value': 8, 'provided': False},
            {'meal': 'LUNCH', 'value': 15, 'provided': True},
            {'meal': 'DINNER', 'value': 20, 'provided': True},
        ]
        response = self.client.patch(
            f'/api/career/applications/{application.id}/',
            {'free_food_meals': entries},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        application.refresh_from_db()
        self.assertEqual(application.free_food_meals, entries)
        # Read back through the API too, since the offer form reads the serialised shape.
        fetched = self.client.get(f'/api/career/applications/{application.id}/').json()
        self.assertEqual(fetched['free_food_meals'], entries)
        # The provided flag must survive as False, not be coerced away.
        self.assertIs(fetched['free_food_meals'][0]['provided'], False)

    def test_legacy_string_list_shape_is_still_accepted(self):
        application = Application.objects.create(
            user=self.user, company=self.company, role_title='Software Engineer', status='OFFER'
        )
        response = self.client.patch(
            f'/api/career/applications/{application.id}/',
            {'free_food_meals': ['LUNCH', 'DINNER'], 'free_food_value_per_meal': '15.00'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        application.refresh_from_db()
        self.assertEqual(application.free_food_meals, ['LUNCH', 'DINNER'])
        self.assertEqual(application.free_food_value_per_meal, Decimal('15.00'))

    def test_defaults_leave_offers_without_free_food_untouched(self):
        application = Application.objects.create(
            user=self.user, company=self.company, role_title='Software Engineer', status='APPLIED'
        )
        self.assertEqual(application.free_food_meals, [])
        self.assertIsNone(application.free_food_value_per_meal)
        # The legacy flat fields still exist, so an offer saved before per-meal keeps its value.
        self.assertEqual(application.free_food_perk_value, 0)
        self.assertEqual(application.free_food_perk_frequency, 'YEARLY')

    def test_legacy_flat_amount_is_preserved_alongside_the_new_fields(self):
        application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title='Software Engineer',
            status='OFFER',
            free_food_perk_value=Decimal('3000'),
            free_food_perk_frequency='YEARLY',
        )
        fetched = self.client.get(f'/api/career/applications/{application.id}/').json()
        self.assertEqual(Decimal(fetched['free_food_perk_value']), Decimal('3000.00'))
        self.assertEqual(fetched['free_food_meals'], [])
