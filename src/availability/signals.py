from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import invalidate_events_cache, invalidate_holidays_cache
from .models import UserSettings

USER_SETTINGS_TZ_CACHE_KEY_PREFIX = "user_settings:primary_timezone"


def get_user_settings_tz_cache_key(user_id):
    return f"{USER_SETTINGS_TZ_CACHE_KEY_PREFIX}:{user_id or 'anonymous'}"


@receiver(post_save, sender=UserSettings)
def invalidate_user_settings_cache(sender, instance, **kwargs):
    try:
        cache.delete(get_user_settings_tz_cache_key(instance.user_id))
        invalidate_events_cache(instance.user_id)
        invalidate_holidays_cache(instance.user_id)
    except Exception:
        pass


@receiver([post_save, post_delete], sender='availability.Event')
def on_event_change(sender, instance, **kwargs):
    try:
        invalidate_events_cache(instance.user_id)
    except Exception:
        pass


@receiver([post_save, post_delete], sender='availability.EventCategory')
def on_category_change(sender, instance, **kwargs):
    try:
        invalidate_events_cache(instance.user_id)
    except Exception:
        pass


@receiver([post_save, post_delete], sender='career.Application')
def on_application_change(sender, instance, **kwargs):
    try:
        invalidate_events_cache(instance.user_id)
    except Exception:
        pass


@receiver([post_save, post_delete], sender='availability.CustomHoliday')
def on_holiday_change(sender, instance, **kwargs):
    try:
        invalidate_holidays_cache(instance.user_id)
        invalidate_events_cache(instance.user_id)
    except Exception:
        pass
