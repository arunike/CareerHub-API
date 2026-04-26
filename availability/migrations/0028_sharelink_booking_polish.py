from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0027_usersettings_ai_provider_adapter'),
    ]

    operations = [
        migrations.AddField(
            model_name='sharelink',
            name='buffer_minutes',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='sharelink',
            name='host_display_name',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='sharelink',
            name='max_bookings_per_day',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='sharelink',
            name='public_note',
            field=models.TextField(blank=True),
        ),
    ]
