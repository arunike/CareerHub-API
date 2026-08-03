from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import (
    invalidate_applications_cache,
    invalidate_experiences_cache,
    invalidate_tasks_cache,
    invalidate_ai_artifacts_cache,
)
from .models import Document, Application, Company, Experience, Task, AIArtifact, ApplicationTimelineEntry
from .services import delete_document_asset
from .services.career_records import (
    ensure_application_career_record,
    ensure_experience_career_record,
)


@receiver(post_delete, sender=Document)
def cleanup_document_file(sender, instance, **kwargs):
    delete_document_asset(instance.file)


@receiver([post_save, post_delete], sender=Application)
def on_application_change(sender, instance, **kwargs):
    if kwargs.get('created'):
        ensure_application_career_record(instance)
    try:
        invalidate_applications_cache(instance.user_id)
    except Exception:
        pass


@receiver([post_save, post_delete], sender=Company)
def on_company_change(sender, instance, **kwargs):
    try:
        invalidate_applications_cache(instance.user_id)
    except Exception:
        pass


@receiver([post_save, post_delete], sender=ApplicationTimelineEntry)
def on_timeline_entry_change(sender, instance, **kwargs):
    try:
        invalidate_applications_cache(instance.user_id)
    except Exception:
        pass


@receiver([post_save, post_delete], sender=Experience)
def on_experience_change(sender, instance, **kwargs):
    if not kwargs.get('signal') == post_delete:
        ensure_experience_career_record(instance)
    try:
        invalidate_experiences_cache(instance.user_id)
    except Exception:
        pass


@receiver([post_save, post_delete], sender=Task)
def on_task_change(sender, instance, **kwargs):
    try:
        invalidate_tasks_cache(instance.user_id)
    except Exception:
        pass


@receiver([post_save, post_delete], sender=AIArtifact)
def on_ai_artifact_change(sender, instance, **kwargs):
    try:
        invalidate_ai_artifacts_cache(instance.user_id)
    except Exception:
        pass
