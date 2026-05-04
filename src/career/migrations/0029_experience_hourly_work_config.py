from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0028_experience_team_history'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='hours_per_day',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Typical hours worked per day for hourly roles',
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='experience',
            name='total_hours_worked',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Optional manual override for total hours worked in an hourly role',
                max_digits=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='experience',
            name='working_days_per_week',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Typical working days per week for hourly roles',
                max_digits=4,
                null=True,
            ),
        ),
    ]
