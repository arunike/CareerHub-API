import re

from django.db import migrations


CANONICAL_STAGE_ORDER = {
    'APPLIED': 0,
    'OA': 10,
    'SCREEN': 20,
    'FINAL_ROUND': 890,
    'ONSITE': 900,
    'OFFER': 1000,
    'REJECTED': 1010,
    'GHOSTED': 1020,
    'REMOVED_FROM_SHEET': 1030,
}


def canonical_stage_order(stage):
    round_match = re.match(r'^ROUND_(\d+)$', stage or '')
    if round_match:
        return 30 + (int(round_match.group(1)) - 1) * 10
    return CANONICAL_STAGE_ORDER.get(stage)


def recalculate_canonical_timeline_order(apps, schema_editor):
    TimelineEntry = apps.get_model('career', 'ApplicationTimelineEntry')
    updates = []
    for entry in TimelineEntry.objects.only('id', 'stage', 'stage_order').iterator():
        next_order = canonical_stage_order(entry.stage)
        if next_order is None or entry.stage_order == next_order:
            continue
        entry.stage_order = next_order
        updates.append(entry)

    if updates:
        TimelineEntry.objects.bulk_update(updates, ['stage_order'])


class Migration(migrations.Migration):
    dependencies = [
        ('career', '0008_editable_timeline_entry_fields'),
    ]

    operations = [
        migrations.RunPython(recalculate_canonical_timeline_order, migrations.RunPython.noop),
    ]
