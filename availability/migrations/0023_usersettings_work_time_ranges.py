from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0022_usersettings_hidden_nav_items'),
    ]

    operations = [
        migrations.AddField(
            model_name='usersettings',
            name='work_time_ranges',
            field=models.JSONField(blank=True, default=list, help_text="List of time ranges [{start: 'HH:MM:SS', end: 'HH:MM:SS'}]. Overrides work_start_time/work_end_time when non-empty."),
        ),
    ]
