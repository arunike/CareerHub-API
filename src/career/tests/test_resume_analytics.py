from datetime import date

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, ApplicationTimelineEntry, Company, Document
from ..services.resume_analytics import (
    MINIMUM_SAMPLE_SIZE,
    role_type_label,
    source_label,
)

URL = '/api/career/resume-version-analytics/'


class SourceLabelTests(APITestCase):
    """The source is read off the job link, so nobody has to type it in."""

    def test_names_a_known_board_however_the_url_was_built(self):
        self.assertEqual(source_label('https://www.linkedin.com/jobs/view/1'), 'LinkedIn')
        self.assertEqual(source_label('https://boards.greenhouse.io/example/jobs/2'), 'Greenhouse')
        self.assertEqual(source_label('https://example.myworkdayjobs.com/en-US/careers'), 'Workday')

    def test_anything_else_with_a_host_is_the_company_site(self):
        self.assertEqual(source_label('https://careers.example.com/roles/3'), 'Company site')

    def test_a_missing_or_unparseable_link_is_not_guessed_at(self):
        self.assertEqual(source_label(''), 'No link')
        self.assertEqual(source_label(None), 'No link')
        self.assertEqual(source_label('not a url'), 'No link')

    def test_a_lookalike_domain_is_not_credited_to_the_board(self):
        self.assertEqual(source_label('https://notlinkedin.com/jobs/1'), 'Company site')


class RoleTypeLabelTests(APITestCase):
    def test_reads_as_words_and_falls_back_rather_than_blanking(self):
        self.assertEqual(role_type_label('full_time'), 'Full-time')
        self.assertEqual(role_type_label('INTERNSHIP'), 'Internship')
        self.assertEqual(role_type_label(''), 'Unspecified')
        self.assertEqual(role_type_label(None), 'Unspecified')


class ResumeVersionAnalyticsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="resume-analytics@example.com",
            email="resume-analytics@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.company = Company.objects.create(user=self.user, name="Google")
        self.v1 = self._resume("Backend Resume", 1)
        self.v2 = self._resume("Backend Resume", 2, root=self.v1)

    def _resume(self, title, version_number, root=None):
        return Document.objects.create(
            user=self.user,
            title=title,
            document_type='RESUME',
            version_number=version_number,
            root_document=root,
        )

    def _application(self, status_value, resume=None, **overrides):
        application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title=overrides.pop('role_title', 'Software Engineer'),
            status=status_value,
            date_applied=overrides.pop('date_applied', date(2026, 7, 1)),
            **overrides,
        )
        if resume:
            application.submitted_documents.add(resume)
        return application

    def _versions(self, response):
        return {row['label']: row for row in response.data['versions']}

    def test_counts_applications_against_the_exact_version_that_was_sent(self):
        self._application('APPLIED', self.v1)
        self._application('APPLIED', self.v1)
        self._application('OFFER', self.v2)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        versions = self._versions(response)
        self.assertEqual(versions['Backend Resume · v1']['applications'], 2)
        self.assertEqual(versions['Backend Resume · v2']['applications'], 1)

    def test_a_later_version_does_not_absorb_the_earlier_one(self):
        self._application('OFFER', self.v1)
        response = self.client.get(URL)
        versions = self._versions(response)
        self.assertEqual(versions['Backend Resume · v1']['offers'], 1)
        self.assertNotIn('Backend Resume · v2', versions)

    def test_rates_are_percentages_of_that_version_alone(self):
        for _ in range(3):
            self._application('APPLIED', self.v1)
        self._application('ONSITE', self.v1)
        response = self.client.get(URL)
        row = self._versions(response)['Backend Resume · v1']
        self.assertEqual(row['applications'], 4)
        self.assertEqual(row['responded'], 1)
        self.assertEqual(row['response_rate'], 25.0)
        self.assertEqual(row['interview_rate'], 25.0)
        self.assertEqual(row['offer_rate'], 0.0)

    def test_an_offer_counts_as_an_interview_even_with_nothing_logged(self):
        self._application('ACCEPTED', self.v1)
        row = self._versions(self.client.get(URL))['Backend Resume · v1']
        self.assertEqual(row['interviewed'], 1)
        self.assertEqual(row['offers'], 1)

    def test_an_interview_that_ended_in_rejection_still_counts_as_one(self):
        application = self._application('REJECTED', self.v1)
        ApplicationTimelineEntry.objects.create(
            user=self.user, application=application, stage='ONSITE', event_date=date(2026, 7, 10)
        )
        row = self._versions(self.client.get(URL))['Backend Resume · v1']
        self.assertEqual(row['interviewed'], 1)
        self.assertEqual(row['responded'], 1)
        self.assertEqual(row['offers'], 0)

    def test_a_ghosted_application_is_not_a_response(self):
        self._application('GHOSTED', self.v1)
        row = self._versions(self.client.get(URL))['Backend Resume · v1']
        self.assertEqual(row['responded'], 0)

    def test_flags_a_sample_too_small_to_read_anything_into(self):
        self._application('OFFER', self.v1)
        row = self._versions(self.client.get(URL))['Backend Resume · v1']
        self.assertEqual(row['offer_rate'], 100.0)
        self.assertTrue(row['below_minimum_sample'])

    def test_clears_the_flag_once_there_are_enough_applications(self):
        for _ in range(MINIMUM_SAMPLE_SIZE):
            self._application('APPLIED', self.v1)
        row = self._versions(self.client.get(URL))['Backend Resume · v1']
        self.assertFalse(row['below_minimum_sample'])

    def test_breaks_performance_down_by_role_type(self):
        self._application('OFFER', self.v1, employment_type='full_time')
        self._application('APPLIED', self.v1, employment_type='internship')
        row = self._versions(self.client.get(URL))['Backend Resume · v1']
        by_role = {entry['label']: entry for entry in row['by_role_type']}
        self.assertEqual(by_role['Full-time']['offer_rate'], 100.0)
        self.assertEqual(by_role['Internship']['offer_rate'], 0.0)

    def test_breaks_performance_down_by_source(self):
        self._application('ONSITE', self.v1, job_link='https://www.linkedin.com/jobs/view/1')
        self._application('APPLIED', self.v1, job_link='https://careers.example.com/2')
        row = self._versions(self.client.get(URL))['Backend Resume · v1']
        by_source = {entry['label']: entry for entry in row['by_source']}
        self.assertEqual(by_source['LinkedIn']['interview_rate'], 100.0)
        self.assertEqual(by_source['Company site']['interview_rate'], 0.0)

    def test_reports_applications_with_no_resume_recorded_rather_than_hiding_them(self):
        self._application('APPLIED', self.v1)
        self._application('APPLIED')
        response = self.client.get(URL)
        self.assertEqual(response.data['total_applications'], 2)
        self.assertEqual(response.data['tracked_applications'], 1)
        self.assertEqual(response.data['untracked_applications'], 1)

    def test_a_cover_letter_sent_alongside_is_not_counted_as_a_resume(self):
        cover_letter = Document.objects.create(
            user=self.user, title="Cover Letter", document_type='COVER_LETTER'
        )
        application = self._application('APPLIED', self.v1)
        application.submitted_documents.add(cover_letter)
        response = self.client.get(URL)
        self.assertEqual(len(response.data['versions']), 1)
        self.assertEqual(response.data['versions'][0]['label'], 'Backend Resume · v1')

    def test_reports_when_each_version_was_first_and_last_used(self):
        self._application('APPLIED', self.v1, date_applied=date(2026, 7, 1))
        self._application('APPLIED', self.v1, date_applied=date(2026, 10, 1))
        row = self._versions(self.client.get(URL))['Backend Resume · v1']
        self.assertEqual(row['first_used'], '2026-07-01')
        self.assertEqual(row['last_used'], '2026-10-01')

    def test_the_year_filter_narrows_the_sample(self):
        self._application('APPLIED', self.v1, date_applied=date(2025, 7, 1))
        self._application('OFFER', self.v1, date_applied=date(2026, 7, 1))
        row = self._versions(self.client.get(URL, {'year': 2026}))['Backend Resume · v1']
        self.assertEqual(row['applications'], 1)
        self.assertEqual(row['offers'], 1)

    def test_the_busiest_version_is_reported_first(self):
        self._application('APPLIED', self.v2)
        for _ in range(3):
            self._application('APPLIED', self.v1)
        labels = [row['label'] for row in self.client.get(URL).data['versions']]
        self.assertEqual(labels, ['Backend Resume · v1', 'Backend Resume · v2'])

    def test_says_nothing_about_another_users_resumes(self):
        stranger = get_user_model().objects.create_user(
            username="stranger-resume@example.com",
            email="stranger-resume@example.com",
            password="StrongPassw0rd!",
        )
        their_company = Company.objects.create(user=stranger, name="Netflix")
        their_resume = Document.objects.create(
            user=stranger, title="Their Resume", document_type='RESUME'
        )
        their_application = Application.objects.create(
            user=stranger, company=their_company, role_title="Software Engineer II", status='OFFER'
        )
        their_application.submitted_documents.add(their_resume)
        self._application('APPLIED', self.v1)
        response = self.client.get(URL)
        self.assertEqual(len(response.data['versions']), 1)
        self.assertEqual(response.data['total_applications'], 1)

    def test_an_empty_account_reports_zeroes_rather_than_failing(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['versions'], [])
        self.assertEqual(response.data['total_applications'], 0)
        self.assertEqual(response.data['overall']['response_rate'], 0.0)

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED)
