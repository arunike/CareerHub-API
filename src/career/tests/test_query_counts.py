import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, Company, Document, Offer


class ApplicationListQueryCountTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="application-query-count@example.com",
            email="application-query-count@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    def test_list_does_not_scale_queries_with_row_count(self):
        """The serializer nests the offer, its experiences and submitted documents."""
        company = Company.objects.create(user=self.user, name='Google')

        def make(index):
            application = Application.objects.create(
                user=self.user,
                company=company,
                role_title=f'Engineer {index}',
                status='OFFER',
                date_applied=timezone.localdate(),
            )
            Offer.objects.create(application=application, base_salary=Decimal('100000'))
            document = Document.objects.create(user=self.user, title=f'Resume {index}')
            application.submitted_documents.add(document)
            return application

        for index in range(2):
            make(index)
        with CaptureQueriesContext(connection) as small:
            self.assertEqual(len(self.client.get('/api/career/applications/').json()), 2)

        for index in range(2, 10):
            make(index)
        with CaptureQueriesContext(connection) as large:
            self.assertEqual(len(self.client.get('/api/career/applications/').json()), 10)

        # The absolute number is not the point; not growing with the row count is.
        self.assertEqual(
            len(large.captured_queries),
            len(small.captured_queries),
            f'5x the rows cost {len(large.captured_queries)} queries instead of '
            f'{len(small.captured_queries)} — a prefetch was probably dropped.',
        )
        self.assertLess(len(large.captured_queries), 10)
