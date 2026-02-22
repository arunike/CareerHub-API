from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0013_application_commute_and_food_perks'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='monthly_rent_override',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='application',
            name='tax_base_rate',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='application',
            name='tax_bonus_rate',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='application',
            name='tax_equity_rate',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
    ]
