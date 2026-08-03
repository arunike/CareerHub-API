from decimal import Decimal, InvalidOperation

from django.db import transaction

from career.models import Application, Offer


OFFER_APPLICATION_STATUSES = {'OFFER', 'ACCEPTED'}


def calculate_realizable_equity(equity, liquidity='LIQUID', buyback_value=0):
    try:
        granted = max(Decimal('0'), Decimal(str(equity or 0)))
        buyback = max(Decimal('0'), Decimal(str(buyback_value or 0)))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')

    if liquidity == 'ILLIQUID':
        return Decimal('0')
    if liquidity == 'BUYBACK':
        return buyback
    return granted


def sync_application_status_for_offer_decision(offer, previous_decision_status):
    application = Application.objects.select_for_update().get(id=offer.application_id)

    if offer.final_decision_status == 'ACCEPTED':
        if application.status != 'ACCEPTED':
            application.status = 'ACCEPTED'
            application.save(update_fields=['status', 'updated_at'])
        return

    if (
        previous_decision_status == 'ACCEPTED'
        and application.status == 'ACCEPTED'
        and not offer.experiences.exists()
    ):
        application.status = 'OFFER'
        application.save(update_fields=['status', 'updated_at'])


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
            'sick_leave_days': 0,
            'sick_leave_included_in_unlimited_pto': True,
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
