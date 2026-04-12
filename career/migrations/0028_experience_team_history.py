from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0027_application_employment_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='team_history',
            field=models.JSONField(blank=True, default=list, help_text='List of team entries [{id, name, start_date, end_date, is_current, norms}]'),
        ),
    ]
