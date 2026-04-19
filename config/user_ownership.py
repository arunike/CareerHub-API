from django.contrib.auth import get_user_model
from django.db import transaction

from availability.models import (
    AvailabilityOverride,
    AvailabilitySetting,
    CustomHoliday,
    Event,
    EventCategory,
    ShareLink,
    UserSettings,
)
from career.models import Application, Company, Document, Experience, Task


OWNED_MODELS = (
    EventCategory,
    CustomHoliday,
    Event,
    UserSettings,
    ShareLink,
    AvailabilityOverride,
    AvailabilitySetting,
    Company,
    Application,
    Document,
    Task,
    Experience,
)


def ensure_user_settings(user):
    settings, _ = UserSettings.objects.get_or_create(user=user)
    return settings


def _owned_records_exist():
    return any(model.objects.exclude(user__isnull=True).exists() for model in OWNED_MODELS)


def _first_registered_user_id():
    user_model = get_user_model()
    return (
        user_model._default_manager.order_by('date_joined', 'id').values_list('id', flat=True).first()
    )


def can_claim_legacy_data(user):
    if not user or not getattr(user, 'id', None):
        return False
    if _owned_records_exist():
        return False
    return user.id == _first_registered_user_id()


def _normalize_legacy_user_settings():
    legacy_settings = list(UserSettings.objects.filter(user__isnull=True).order_by('id'))
    if len(legacy_settings) <= 1:
        return

    drop_ids = [settings.id for settings in legacy_settings[1:]]
    if drop_ids:
        UserSettings.objects.filter(id__in=drop_ids).delete()


def _normalize_legacy_companies():
    legacy_companies = Company.objects.filter(user__isnull=True).order_by('id')
    seen_by_name = {}
    duplicate_ids = []

    for company in legacy_companies:
        primary = seen_by_name.get(company.name)
        if primary is None:
            seen_by_name[company.name] = company
            continue

        Application.objects.filter(company=company).update(company=primary)
        duplicate_ids.append(company.id)

    if duplicate_ids:
        Company.objects.filter(id__in=duplicate_ids).delete()


@transaction.atomic
def claim_legacy_records_for_user(user):
    if not can_claim_legacy_data(user):
        return False

    _normalize_legacy_user_settings()
    _normalize_legacy_companies()

    claimed_any = False
    for model in OWNED_MODELS:
        updated = model.objects.filter(user__isnull=True).update(user=user)
        claimed_any = claimed_any or updated > 0

    ensure_user_settings(user)
    return claimed_any
