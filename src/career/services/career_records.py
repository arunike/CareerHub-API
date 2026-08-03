from django.db import transaction

from career.models import CareerRecord


def ensure_application_career_record(application):
    record, _ = CareerRecord.objects.get_or_create(
        application=application,
        defaults={'user_id': application.user_id},
    )
    if record.user_id != application.user_id:
        CareerRecord.objects.filter(id=record.id).update(user_id=application.user_id)
        record.user_id = application.user_id
    return record


def ensure_experience_career_record(experience):
    with transaction.atomic():
        if experience.offer_id:
            application = experience.offer.application
            record = ensure_application_career_record(application)
            if application.status != 'ACCEPTED':
                application.status = 'ACCEPTED'
                application.save(update_fields=['status', 'updated_at'])
        elif experience.career_record_id:
            record = experience.career_record
        else:
            record = CareerRecord.objects.create(user_id=experience.user_id)

        if experience.career_record_id != record.id:
            type(experience).objects.filter(id=experience.id).update(career_record=record)
            experience.career_record_id = record.id
        return record
