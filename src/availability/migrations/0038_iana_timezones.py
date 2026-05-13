from django.db import migrations, models


LEGACY_TIMEZONE_ALIASES = {
    'PT': 'America/Los_Angeles',
    'MT': 'America/Denver',
    'CT': 'America/Chicago',
    'ET': 'America/New_York',
}


def expand_legacy_timezones(apps, schema_editor):
    Event = apps.get_model('availability', 'Event')
    PublicBooking = apps.get_model('availability', 'PublicBooking')

    for old_value, new_value in LEGACY_TIMEZONE_ALIASES.items():
        Event.objects.filter(timezone=old_value).update(timezone=new_value)
        PublicBooking.objects.filter(timezone=old_value).update(timezone=new_value)


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0037_alter_usersettings_availability_weeks'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='timezone',
            field=models.CharField(default='America/Los_Angeles', max_length=64),
        ),
        migrations.AlterField(
            model_name='publicbooking',
            name='timezone',
            field=models.CharField(default='America/Los_Angeles', max_length=64),
        ),
        migrations.RunPython(expand_legacy_timezones, migrations.RunPython.noop),
    ]
