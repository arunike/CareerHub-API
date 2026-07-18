from django.db import migrations, models


def protect_existing_timeline_content(apps, schema_editor):
    TimelineEntry = apps.get_model('career', 'ApplicationTimelineEntry')
    TimelineEntry.objects.filter(event_date__isnull=False).update(
        event_date_is_user_override=True,
    )
    TimelineEntry.objects.exclude(notes='').update(
        notes_is_user_override=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0007_offer_sick_leave_unlimited_policy'),
    ]

    operations = [
        migrations.AddField(
            model_name='applicationtimelineentry',
            name='display_title',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='applicationtimelineentry',
            name='event_date_is_user_override',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='applicationtimelineentry',
            name='notes_is_user_override',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='applicationtimelineentry',
            name='deleted_by_user_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='applicationtimelineentry',
            name='hidden_by_sync_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(protect_existing_timeline_content, migrations.RunPython.noop),
    ]
