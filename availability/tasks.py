from celery import shared_task
from django.core.cache import cache
from django.utils import timezone


@shared_task(name="availability.tasks.expire_stale_share_links")
def expire_stale_share_links():
    from availability.models import ShareLink

    count = ShareLink.objects.filter(is_active=True, expires_at__lte=timezone.now()).update(
        is_active=False
    )
    return f"Deactivated {count} expired share link(s)."


@shared_task(name="availability.tasks.clear_widget_cache")
def clear_widget_cache():
    cache.clear()
    return "Widget cache cleared."
