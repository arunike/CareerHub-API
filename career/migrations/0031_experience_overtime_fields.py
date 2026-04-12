from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0030_experience_total_earnings_override'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='overtime_hours',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Optional overtime hours worked in an hourly role',
                max_digits=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='experience',
            name='overtime_multiplier',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Optional overtime multiplier when overtime rate is derived from hourly rate',
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='experience',
            name='overtime_rate',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Optional explicit overtime hourly rate',
                max_digits=8,
                null=True,
            ),
        ),
    ]
