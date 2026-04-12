from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0031_experience_overtime_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='schedule_phases',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='List of schedule phases [{id, name, start_date, end_date, is_current, hourly_rate, hours_per_day, working_days_per_week, total_hours_worked, overtime_hours, overtime_rate, overtime_multiplier, total_earnings_override}]'
            ),
        ),
    ]
