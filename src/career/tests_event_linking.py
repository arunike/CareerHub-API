"""The rule that decides which application a calendar event belongs to."""

from datetime import date, timedelta

from django.test import SimpleTestCase

from career.services.event_linking import (
    APPLIED_AFTER_GRACE_DAYS,
    build_company_index,
    confidence_for,
    eligible_applications,
    match_company,
    pick_application,
)


class FakeApplication:
    def __init__(self, role_title, status='APPLIED', date_applied=None):
        self.role_title = role_title
        self.status = status
        self.date_applied = date_applied

    def __repr__(self):
        return f'<{self.role_title}>'


class MatchCompanyTests(SimpleTestCase):
    def setUp(self):
        self.companies = build_company_index([(1, 'Google'), (2, 'Sony Interactive'), (3, 'Sony')])

    def test_matches_a_company_named_in_the_title(self):
        self.assertEqual(match_company('Interview with Google', self.companies), (1, 'Google'))

    def test_prefers_the_longer_name(self):
        self.assertEqual(
            match_company('Interview with Sony Interactive Entertainment', self.companies),
            (2, 'Sony Interactive'),
        )

    def test_ignores_a_meeting_platform(self):
        self.assertIsNone(match_company('Wisk Google Meet Interview', self.companies))

    def test_drops_names_too_short_to_match_on(self):
        self.assertEqual(build_company_index([(1, 'AI'), (2, 'Eve')]), [(2, 'Eve')])


class EligibilityTests(SimpleTestCase):
    def test_keeps_an_application_submitted_before_the_event(self):
        app = FakeApplication('Software Engineer', date_applied=date(2026, 1, 10))
        self.assertEqual(eligible_applications([app], date(2026, 2, 1)), [app])

    def test_drops_an_application_submitted_long_after_the_event(self):
        # The real case: a 2025 interview against an application first logged in 2026.
        app = FakeApplication('Software Engineer', date_applied=date(2026, 5, 13))
        self.assertEqual(eligible_applications([app], date(2025, 2, 7)), [])

    def test_allows_the_grace_window_for_late_data_entry(self):
        event = date(2026, 3, 1)
        inside = FakeApplication('A', date_applied=event + timedelta(days=APPLIED_AFTER_GRACE_DAYS))
        outside = FakeApplication(
            'B', date_applied=event + timedelta(days=APPLIED_AFTER_GRACE_DAYS + 1)
        )
        self.assertEqual(eligible_applications([inside, outside], event), [inside])

    def test_keeps_an_application_with_no_date(self):
        app = FakeApplication('Software Engineer', date_applied=None)
        self.assertEqual(eligible_applications([app], date(2025, 1, 1)), [app])

    def test_keeps_everything_when_the_event_has_no_date(self):
        apps = [FakeApplication('A', date_applied=date(2030, 1, 1))]
        self.assertEqual(eligible_applications(apps, None), apps)


class PickApplicationTests(SimpleTestCase):
    def test_returns_nothing_when_every_application_postdates_the_event(self):
        apps = [FakeApplication(f'Role {i}', date_applied=date(2026, 5, 13)) for i in range(9)]
        self.assertIsNone(pick_application(apps, date(2025, 2, 7)))

    def test_prefers_an_application_already_in_interview(self):
        applied = FakeApplication('Applied', 'APPLIED', date(2026, 1, 1))
        interviewing = FakeApplication('Interviewing', 'ROUND_2', date(2026, 1, 1))
        self.assertIs(pick_application([applied, interviewing], date(2026, 2, 1)), interviewing)

    def test_prefers_the_application_submitted_closest_before_the_event(self):
        near = FakeApplication('Near', 'APPLIED', date(2026, 1, 20))
        far = FakeApplication('Far', 'APPLIED', date(2025, 1, 20))
        self.assertIs(pick_application([near, far], date(2026, 2, 1)), near)

    def test_returns_the_only_candidate_without_weighing_it(self):
        only = FakeApplication('Only', 'REJECTED', date(2026, 1, 1))
        self.assertIs(pick_application([only], date(2026, 2, 1)), only)


class ConfidenceTests(SimpleTestCase):
    def test_a_single_candidate_is_high(self):
        self.assertEqual(confidence_for('Robinhood', 1), 'high')

    def test_several_candidates_at_a_long_named_company_is_medium(self):
        self.assertEqual(confidence_for('Pinterest', 3), 'medium')

    def test_several_candidates_at_a_short_named_company_is_low(self):
        self.assertEqual(confidence_for('Uber', 4), 'low')
