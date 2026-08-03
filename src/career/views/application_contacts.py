from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import Contact, ContactContext, ContactRelationship, Experience
from ..serializers import ContactRelationshipSerializer, ContactSerializer


class ApplicationContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer

    def get_queryset(self):
        queryset = Contact.objects.filter(user=self.request.user).prefetch_related(
            'contexts__application__company',
            'contexts__experience',
        )

        application = (self.request.query_params.get('application') or '').strip()
        if application:
            try:
                return queryset.filter(contexts__application_id=int(application)).distinct()
            except ValueError:
                return queryset.none()

        experience = (self.request.query_params.get('experience') or '').strip()
        if experience:
            try:
                experience_obj = Experience.objects.select_related('offer').get(
                    id=int(experience), user=self.request.user
                )
            except (ValueError, Experience.DoesNotExist):
                return queryset.none()
            application_id = getattr(experience_obj.offer, 'application_id', None)
            owner_filter = Q(contexts__experience_id=experience_obj.id)
            if application_id:
                owner_filter |= Q(contexts__application_id=application_id)
            return queryset.filter(owner_filter).distinct()

        search = (self.request.query_params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(job_title__icontains=search)
                | Q(company__icontains=search)
                | Q(notes__icontains=search)
                | Q(contexts__application__company__name__icontains=search)
                | Q(contexts__application__role_title__icontains=search)
                | Q(contexts__experience__company__icontains=search)
                | Q(contexts__experience__title__icontains=search)
                | Q(incoming_relationships__custom_label__icontains=search)
                | Q(outgoing_relationships__custom_label__icontains=search)
            )

        context_type = (self.request.query_params.get('context') or '').upper()
        if context_type == 'APPLICATION':
            queryset = queryset.filter(contexts__application__isnull=False)
        elif context_type == 'EXPERIENCE':
            queryset = queryset.filter(contexts__experience__isnull=False)

        relationship = (self.request.query_params.get('relationship') or '').upper()
        if relationship:
            queryset = queryset.filter(
                Q(incoming_relationships__user=self.request.user, incoming_relationships__kind=relationship)
                | Q(outgoing_relationships__user=self.request.user, outgoing_relationships__kind=relationship)
            )

        direct = (self.request.query_params.get('direct') or '').lower()
        if direct == 'true':
            queryset = queryset.filter(
                incoming_relationships__user=self.request.user,
                incoming_relationships__source_contact__isnull=True,
            )
        elif direct == 'false':
            queryset = queryset.exclude(
                incoming_relationships__user=self.request.user,
                incoming_relationships__source_contact__isnull=True,
            )
        return queryset.distinct()

    def _mark_list_metadata(self, contacts):
        names = defaultdict(list)
        for contact in contacts:
            names[contact.name.strip().casefold()].append(contact)
        for group in names.values():
            if len(group) > 1:
                for contact in group:
                    contact._possible_duplicate = True

        experience_id = (self.request.query_params.get('experience') or '').strip()
        if not experience_id:
            return
        try:
            experience = Experience.objects.select_related('offer').get(
                id=int(experience_id), user=self.request.user
            )
        except (ValueError, Experience.DoesNotExist):
            return
        application_id = getattr(experience.offer, 'application_id', None)
        for contact in contacts:
            has_experience = any(
                context.experience_id == experience.id for context in contact.contexts.all()
            )
            has_application = application_id and any(
                context.application_id == application_id for context in contact.contexts.all()
            )
            contact._inherited = bool(has_application and not has_experience)

    def list(self, request, *args, **kwargs):
        contacts = list(self.get_queryset())
        self._mark_list_metadata(contacts)
        return Response(self.get_serializer(contacts, many=True).data)

    def destroy(self, request, *args, **kwargs):
        contact = self.get_object()
        application = (request.query_params.get('application') or '').strip()
        experience = (request.query_params.get('experience') or '').strip()
        if application or experience:
            contexts = ContactContext.objects.filter(contact=contact)
            try:
                if application:
                    contexts = contexts.filter(application_id=int(application))
                if experience:
                    contexts = contexts.filter(experience_id=int(experience))
            except ValueError:
                return Response(status=status.HTTP_404_NOT_FOUND)
            contexts.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        if contact.is_locked:
            return Response(
                {'detail': 'Unlock this contact before deleting it.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def merge(self, request, pk=None):
        contact = self.get_object()
        duplicate_id = request.data.get('duplicate_id')
        duplicate = Contact.objects.filter(id=duplicate_id, user=request.user).first()
        if duplicate is None or duplicate.id == contact.id:
            return Response(
                {'duplicate_id': 'Choose another contact from your account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            changed_fields = []
            for field in ['email', 'job_title', 'company']:
                if not getattr(contact, field) and getattr(duplicate, field):
                    setattr(contact, field, getattr(duplicate, field))
                    changed_fields.append(field)
            if duplicate.notes and duplicate.notes not in contact.notes:
                contact.notes = f'{contact.notes.strip()}\n\n{duplicate.notes.strip()}'.strip()
                changed_fields.append('notes')
            if duplicate.is_locked and not contact.is_locked:
                contact.is_locked = True
                changed_fields.append('is_locked')
            if changed_fields:
                contact.save(update_fields=[*changed_fields, 'updated_at'])

            for context in duplicate.contexts.all():
                existing, created = ContactContext.objects.get_or_create(
                    contact=contact,
                    application=context.application,
                    experience=context.experience,
                    defaults={
                        'career_record': context.career_record,
                        'source': context.source,
                        'notes': context.notes,
                    },
                )
                if not created and context.notes and context.notes not in existing.notes:
                    existing.notes = f'{existing.notes.strip()}\n\n{context.notes.strip()}'.strip()
                    existing.save(update_fields=['notes'])

            ContactRelationship.objects.filter(source_contact=duplicate).update(source_contact=contact)
            ContactRelationship.objects.filter(target_contact=duplicate).update(target_contact=contact)
            ContactRelationship.objects.filter(source_contact=contact, target_contact=contact).delete()

            seen = set()
            relationships = ContactRelationship.objects.filter(user=request.user).filter(
                Q(source_contact=contact) | Q(target_contact=contact)
            ).order_by('id')
            for relationship in relationships:
                key = (
                    relationship.source_contact_id,
                    relationship.target_contact_id,
                    relationship.kind,
                    relationship.custom_label.casefold(),
                )
                if key in seen:
                    relationship.delete()
                else:
                    seen.add(key)
            duplicate.delete()

        contact = self.get_queryset().get(id=contact.id)
        return Response(self.get_serializer(contact).data)


class ContactRelationshipViewSet(viewsets.ModelViewSet):
    serializer_class = ContactRelationshipSerializer

    def get_queryset(self):
        queryset = ContactRelationship.objects.filter(user=self.request.user).select_related(
            'source_contact', 'target_contact', 'career_record'
        )
        contact = (self.request.query_params.get('contact') or '').strip()
        if contact:
            try:
                contact_id = int(contact)
            except ValueError:
                return queryset.none()
            queryset = queryset.filter(
                Q(source_contact_id=contact_id) | Q(target_contact_id=contact_id)
            )
        return queryset
