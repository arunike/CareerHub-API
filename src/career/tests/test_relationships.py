import json

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Application, CareerRecord, Company, Contact, ContactContext, ContactRelationship, Experience, Offer


class CareerRelationshipNetworkTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='relationships@example.com',
            email='relationships@example.com',
            password='StrongPassw0rd!',
        )
        self.client.force_authenticate(self.user)
        self.company = Company.objects.create(user=self.user, name='Northstar Labs')
        self.application = Application.objects.create(
            user=self.user,
            company=self.company,
            role_title='Platform Engineer',
            status='OFFER',
        )

    def test_application_gets_one_shared_career_record(self):
        record = CareerRecord.objects.get(application=self.application)

        self.assertEqual(record.user, self.user)
        self.assertEqual(self.application.career_record, record)

    def test_embedded_contact_create_adds_context_and_direct_relationship(self):
        response = self.client.post(
            '/api/career/contacts/',
            {
                'application': self.application.id,
                'name': 'Avery Morgan',
                'email': 'AVERY@EXAMPLE.COM',
                'relationship_kind': 'INTERVIEWER',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        contact = Contact.objects.get(user=self.user)
        self.assertEqual(contact.email, 'avery@example.com')
        self.assertTrue(
            ContactContext.objects.filter(contact=contact, application=self.application).exists()
        )
        self.assertTrue(
            ContactRelationship.objects.filter(
                user=self.user,
                source_contact=None,
                target_contact=contact,
                kind='INTERVIEWER',
            ).exists()
        )

    def test_experience_reuses_email_contact_and_accepts_linked_application(self):
        contact_response = self.client.post(
            '/api/career/contacts/',
            {
                'application': self.application.id,
                'name': 'Rowan Patel',
                'email': 'rowan@example.com',
            },
            format='json',
        )
        offer = Offer.objects.create(application=self.application, base_salary=180000)

        experience_response = self.client.post(
            '/api/career/experiences/',
            {
                'title': 'Platform Engineer',
                'company': 'Northstar Labs',
                'offer': offer.id,
                'is_current': True,
            },
            format='json',
        )
        self.assertEqual(experience_response.status_code, status.HTTP_201_CREATED)
        experience_id = experience_response.data['id']
        second_contact_response = self.client.post(
            '/api/career/contacts/',
            {
                'experience': experience_id,
                'name': 'Rowan P.',
                'email': 'ROWAN@example.com',
                'relationship_kind': 'COWORKER',
            },
            format='json',
        )

        self.assertEqual(contact_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_contact_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Contact.objects.filter(user=self.user).count(), 1)
        self.assertEqual(ContactContext.objects.filter(contact__user=self.user).count(), 2)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'ACCEPTED')
        experience = Experience.objects.get(id=experience_id)
        self.assertEqual(experience.career_record, self.application.career_record)

    def test_indirect_custom_relationship_does_not_create_self_edge(self):
        direct = Contact.objects.create(user=self.user, name='John Smith')
        indirect = Contact.objects.create(user=self.user, name='Alex Kim')
        ContactRelationship.objects.create(
            user=self.user,
            source_contact=None,
            target_contact=direct,
            kind='COWORKER',
        )

        response = self.client.post(
            '/api/career/contact-relationships/',
            {
                'source_contact': direct.id,
                'target_contact': indirect.id,
                'kind': 'CUSTOM',
                'custom_label': 'Skip-level manager',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(
            ContactRelationship.objects.filter(
                user=self.user,
                source_contact=None,
                target_contact=indirect,
            ).exists()
        )

    def test_scoped_delete_detaches_context_without_deleting_person(self):
        response = self.client.post(
            '/api/career/contacts/',
            {'application': self.application.id, 'name': 'Taylor Brooks'},
            format='json',
        )
        contact_id = response.data['id']

        delete_response = self.client.delete(
            f'/api/career/contacts/{contact_id}/?application={self.application.id}'
        )

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(Contact.objects.filter(id=contact_id).exists())
        self.assertFalse(ContactContext.objects.filter(contact_id=contact_id).exists())

    def test_same_name_contacts_are_flagged_but_not_merged(self):
        Contact.objects.create(user=self.user, name='Alex Kim', email='alex.one@example.com')
        Contact.objects.create(user=self.user, name='Alex Kim', email='alex.two@example.com')

        response = self.client.get('/api/career/contacts/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertTrue(all(item['possible_duplicate'] for item in response.data))
