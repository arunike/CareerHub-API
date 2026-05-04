from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Document
from .services import delete_document_asset


@receiver(post_delete, sender=Document)
def cleanup_document_file(sender, instance, **kwargs):
    delete_document_asset(instance.file)
