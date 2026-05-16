from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0038_iana_timezones'),
    ]

    operations = [
        migrations.AddField(
            model_name='sharelink',
            name='reschedule_cancel_deadline_hours',
            field=models.IntegerField(
                default=0,
                help_text='Minimum hours before a booking when public reschedule/cancel remains available. 0 disables the cutoff.',
            ),
        ),
        migrations.AddField(
            model_name='publicbooking',
            name='cancel_reason',
            field=models.TextField(blank=True),
        ),
    ]
