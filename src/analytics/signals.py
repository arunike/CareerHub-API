from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from availability.models import Event
from career.models import Application


def _bust_widget_cache(*args, **kwargs):
    try:
        cache.clear()
    except Exception:
        pass


# Connect the same handler to all four relevant signals
post_save.connect(_bust_widget_cache, sender=Event)
post_delete.connect(_bust_widget_cache, sender=Event)
post_save.connect(_bust_widget_cache, sender=Application)
post_delete.connect(_bust_widget_cache, sender=Application)
