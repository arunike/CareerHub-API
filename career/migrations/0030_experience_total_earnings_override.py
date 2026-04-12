from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0029_experience_hourly_work_config'),
        ('career', '0029_experience_is_pinned'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='total_earnings_override',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Optional manual override for total internship earnings',
                max_digits=12,
                null=True,
            ),
        ),
    ]
