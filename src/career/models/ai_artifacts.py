import re
from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class AIArtifact(models.Model):
    TYPE_JD_REPORT = 'JD_REPORT'
    TYPE_COVER_LETTER = 'COVER_LETTER'
    TYPE_NEGOTIATION_RESULT = 'NEGOTIATION_RESULT'
    TYPE_PROMOTION_REVIEW = 'PROMOTION_REVIEW'
    ARTIFACT_TYPE_CHOICES = [
        (TYPE_JD_REPORT, 'JD Report'),
        (TYPE_COVER_LETTER, 'Cover Letter'),
        (TYPE_NEGOTIATION_RESULT, 'Negotiation Result'),
        (TYPE_PROMOTION_REVIEW, 'Promotion Review'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_artifacts')
    artifact_type = models.CharField(max_length=40, choices=ARTIFACT_TYPE_CHOICES)
    client_id = models.CharField(max_length=120)
    title = models.CharField(max_length=255, blank=True)
    summary = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    source_application = models.ForeignKey(
        'career.Application',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_artifacts',
    )
    source_experience = models.ForeignKey(
        'Experience',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name='ai_artifacts',
    )
    is_locked = models.BooleanField(default=False)
    saved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-saved_at', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'client_id'], name='unique_ai_artifact_client_id_per_user'),
        ]

    def __str__(self):
        return self.title or f"{self.artifact_type} {self.client_id}"


class AIArtifactGenerationJob(models.Model):
    STATUS_QUEUED = 'QUEUED'
    STATUS_RUNNING = 'RUNNING'
    STATUS_SUCCEEDED = 'SUCCEEDED'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCEEDED, 'Succeeded'),
        (STATUS_FAILED, 'Failed'),
    ]

    KIND_PROMOTION_REVIEW = 'PROMOTION_REVIEW'
    KIND_CHOICES = [
        (KIND_PROMOTION_REVIEW, 'Promotion Review'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_artifact_generation_jobs')
    kind = models.CharField(max_length=40, choices=KIND_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    input_payload = models.JSONField(default=dict, blank=True)
    result_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    artifact = models.ForeignKey(
        AIArtifact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generation_jobs',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.kind} job {self.id} ({self.status})"
