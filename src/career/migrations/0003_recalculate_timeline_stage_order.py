import re

from django.db import migrations


DEFAULT_TIMELINE_STAGE_ORDER = {
    'APPLIED': 0,
    'OA': 10,
    'SCREEN': 20,
    'ONSITE': 900,
    'OFFER': 1000,
    'REJECTED': 1010,
    'GHOSTED': 1020,
    'REMOVED_FROM_SHEET': 1030,
}


def stage_order(stage):
    round_match = re.match(r'^ROUND_(\d+)$', stage or '')
    if round_match:
        return 30 + (int(round_match.group(1)) - 1) * 10
    return DEFAULT_TIMELINE_STAGE_ORDER.get(stage)


def recalculate_timeline_stage_order(apps, schema_editor):
    ApplicationTimelineEntry = apps.get_model('career', 'ApplicationTimelineEntry')
    updates = []
    for entry in ApplicationTimelineEntry.objects.only('id', 'stage', 'stage_order').iterator():
        next_order = stage_order(entry.stage)
        if next_order is None or entry.stage_order == next_order:
            continue
        entry.stage_order = next_order
        updates.append(entry)

    if updates:
        ApplicationTimelineEntry.objects.bulk_update(updates, ['stage_order'])


class Migration(migrations.Migration):
    dependencies = [
        ('career', '0002_application_flexible_hours_policy_and_more'),
    ]

    operations = [
        migrations.RunPython(recalculate_timeline_stage_order, migrations.RunPython.noop),
    ]
