from django.db import transaction

from career.models import Application, Offer


OFFER_APPLICATION_STATUSES = {'OFFER', 'ACCEPTED'}


def ensure_offer_for_application(application):
    if application.status not in OFFER_APPLICATION_STATUSES:
        return None

    offer, _ = Offer.objects.get_or_create(
        application=application,
        defaults={
            'base_salary': 0,
            'bonus': 0,
            'equity': 0,
            'sign_on': 0,
            'benefits_value': 0,
            'benefit_items': [],
            'pto_days': 15,
            'is_unlimited_pto': False,
            'holiday_days': 11,
            'is_current': application.status == 'ACCEPTED',
        },
    )
    return offer


def ensure_offers_for_offer_status_applications(user):
    application_ids = list(Application.objects.filter(
        user=user,
        status__in=OFFER_APPLICATION_STATUSES,
        offer__isnull=True,
    ).values_list('id', flat=True))
    if not application_ids:
        return

    with transaction.atomic():
        for application in Application.objects.filter(id__in=application_ids).select_for_update():
            ensure_offer_for_application(application)
