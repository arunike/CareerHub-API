from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0012_application_rto_days_per_week'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='commute_cost_frequency',
            field=models.CharField(
                choices=[('DAILY', 'Daily'), ('MONTHLY', 'Monthly'), ('YEARLY', 'Yearly')],
                default='MONTHLY',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='application',
            name='commute_cost_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='application',
            name='free_food_perk_frequency',
            field=models.CharField(
                choices=[('DAILY', 'Daily'), ('MONTHLY', 'Monthly'), ('YEARLY', 'Yearly')],
                default='YEARLY',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='application',
            name='free_food_perk_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
