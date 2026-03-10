from celery import shared_task
from django.utils import timezone
from datetime import timedelta

PENDING_STATUSES = ("APPLIED", "OA", "SCREEN", "ONSITE")
DEFAULT_GHOSTING_THRESHOLD_DAYS = 30


@shared_task(name="career.tasks.auto_ghost_stale_applications")
def auto_ghost_stale_applications():
    from career.models import Application
    from availability.models import UserSettings

    settings = UserSettings.objects.first()
    threshold_days = (
        settings.ghosting_threshold_days if settings else DEFAULT_GHOSTING_THRESHOLD_DAYS
    )

    cutoff_date = timezone.now() - timedelta(days=threshold_days)
    stale_applications = Application.objects.filter(
        status__in=PENDING_STATUSES,
        updated_at__lte=cutoff_date,
    )
    count = stale_applications.update(status="GHOSTED")
    return f"Ghosted {count} stale application(s)."
