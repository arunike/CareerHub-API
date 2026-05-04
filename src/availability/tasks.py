from django.core.cache import cache
from django.utils import timezone


def expire_stale_share_links():
    from availability.models import ShareLink

    count = ShareLink.objects.filter(is_active=True, expires_at__lte=timezone.now()).update(
        is_active=False
    )
    return f"Deactivated {count} expired share link(s)."


def purge_expired_account_deletions():
    from django.contrib.auth import get_user_model
    from availability.models import UserSettings

    user_ids = list(
        UserSettings.objects.filter(
            user__isnull=False,
            account_deletion_scheduled_for__isnull=False,
            account_deletion_scheduled_for__lte=timezone.now(),
        ).values_list("user_id", flat=True)
    )

    if not user_ids:
        return "Deleted 0 expired account(s)."

    deleted_count = get_user_model().objects.filter(id__in=user_ids).count()
    get_user_model().objects.filter(id__in=user_ids).delete()
    return f"Deleted {deleted_count} expired account(s)."


def clear_widget_cache():
    cache.clear()
    return "Widget cache cleared."
