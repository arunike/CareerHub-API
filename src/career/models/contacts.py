import re
from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class CareerRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='career_records'
    )
    application = models.OneToOneField(
        'career.Application',
        on_delete=models.CASCADE,
        related_name='career_record',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']

    def __str__(self):
        if self.application_id:
            return str(self.application)
        experience = self.experiences.order_by('-is_current', '-start_date', '-id').first()
        return str(experience) if experience else f'Career record {self.id}'


class Contact(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='career_contacts'
    )
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    job_title = models.CharField(max_length=255, blank=True)
    company = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']
        indexes = [
            models.Index(fields=['user', 'name'], name='career_person_name_idx'),
            models.Index(fields=['user', 'email'], name='career_person_email_idx'),
        ]

    def __str__(self):
        return self.name


class ContactContext(models.Model):
    SOURCE_CHOICES = [
        ('APPLICATION', 'Application'),
        ('EXPERIENCE', 'Experience'),
        ('MANUAL', 'Manual'),
    ]

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='contexts')
    career_record = models.ForeignKey(
        CareerRecord, on_delete=models.CASCADE, related_name='contact_contexts'
    )
    application = models.ForeignKey(
        'career.Application',
        on_delete=models.CASCADE,
        related_name='contact_contexts',
        null=True,
        blank=True,
    )
    experience = models.ForeignKey(
        'Experience',
        on_delete=models.CASCADE,
        related_name='contact_contexts',
        null=True,
        blank=True,
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['career_record', 'contact'], name='career_context_record_idx'),
            models.Index(fields=['application', 'contact'], name='career_context_app_idx'),
            models.Index(fields=['experience', 'contact'], name='career_context_exp_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(application__isnull=False) | models.Q(experience__isnull=False),
                name='contact_context_has_owner',
            ),
        ]


class ContactRelationship(models.Model):
    KIND_CHOICES = [
        ('CONTACT', 'Contact'),
        ('RECRUITER', 'Recruiter'),
        ('INTERVIEWER', 'Interviewer'),
        ('HIRING_MANAGER', 'Hiring Manager'),
        ('MANAGER', 'Manager'),
        ('DIRECT_TEAMMATE', 'Direct Teammate'),
        ('COWORKER', 'Coworker'),
        ('TECH_LEAD', 'Tech Lead'),
        ('MENTOR', 'Mentor'),
        ('WORKS_WITH', 'Works With'),
        ('CUSTOM', 'Custom'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contact_relationships'
    )
    # A null source represents the signed-in user at the center of the graph.
    source_contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name='outgoing_relationships',
        null=True,
        blank=True,
    )
    target_contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name='incoming_relationships'
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES, default='CONTACT')
    custom_label = models.CharField(max_length=80, blank=True)
    career_record = models.ForeignKey(
        CareerRecord,
        on_delete=models.SET_NULL,
        related_name='contact_relationships',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['user', 'source_contact'], name='career_rel_source_idx'),
            models.Index(fields=['user', 'target_contact'], name='career_rel_target_idx'),
        ]

    def __str__(self):
        source = self.source_contact.name if self.source_contact_id else 'Me'
        label = self.custom_label if self.kind == 'CUSTOM' else self.get_kind_display()
        return f'{source} - {label} - {self.target_contact.name}'
