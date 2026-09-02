from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserSettings

USER_SETTINGS_TZ_CACHE_KEY_PREFIX = "user_settings:primary_timezone"


def get_user_settings_tz_cache_key(user_id):
    return f"{USER_SETTINGS_TZ_CACHE_KEY_PREFIX}:{user_id or 'anonymous'}"


@receiver(post_save, sender=UserSettings)
def invalidate_user_settings_cache(sender, instance, **kwargs):
    try:
        cache.delete(get_user_settings_tz_cache_key(instance.user_id))
    except Exception:
        pass
