from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserSettings

USER_SETTINGS_TZ_CACHE_KEY = "user_settings:primary_timezone"


@receiver(post_save, sender=UserSettings)
def invalidate_user_settings_cache(sender, instance, **kwargs):
    try:
        cache.delete(USER_SETTINGS_TZ_CACHE_KEY)
    except Exception:
        pass
