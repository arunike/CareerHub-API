import re
from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Document(models.Model):
    DOCUMENT_TYPES = [
        ('RESUME', 'Resume'),
        ('COVER_LETTER', 'Cover Letter'),
        ('OFFER_LETTER', 'Offer Letter'),
        ('PORTFOLIO', 'Portfolio'),
        ('OTHER', 'Other'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='documents')
    title = models.CharField(max_length=255)
    file = models.URLField(max_length=2048, null=True, blank=True)
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default='RESUME')
    application = models.ForeignKey('career.Application', on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    root_document = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='versions')
    version_number = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False, help_text="Locked documents cannot be deleted")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} (v{self.version_number})"


