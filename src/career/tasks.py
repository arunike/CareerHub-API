from datetime import timedelta

from django.utils import timezone

PENDING_STATUSES = ("APPLIED", "OA", "SCREEN", "ONSITE")
DEFAULT_GHOSTING_THRESHOLD_DAYS = 30


def auto_ghost_stale_applications():
    from career.models import Application
    from availability.models import UserSettings

    count = 0
    user_settings_map = {
        settings.user_id: settings.ghosting_threshold_days or DEFAULT_GHOSTING_THRESHOLD_DAYS
        for settings in UserSettings.objects.exclude(user__isnull=True)
    }

    for user_id in Application.objects.exclude(user__isnull=True).values_list('user_id', flat=True).distinct():
        threshold_days = user_settings_map.get(user_id, DEFAULT_GHOSTING_THRESHOLD_DAYS)
        cutoff_date = timezone.now() - timedelta(days=threshold_days)
        stale_applications = Application.objects.filter(
            user_id=user_id,
            status__in=PENDING_STATUSES,
            updated_at__lte=cutoff_date,
        )
        count += stale_applications.update(status="GHOSTED")

    return f"Ghosted {count} stale application(s)."
