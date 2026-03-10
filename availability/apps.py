from django.apps import AppConfig


class AvailabilityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "availability"

    def ready(self):
        import availability.signals  # noqa: F401  registers UserSettings cache-invalidation handler
