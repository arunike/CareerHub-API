from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0016_offer_benefit_items'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='equity_total_grant',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Total equity grant value', max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='offer',
            name='equity_vesting_percent',
            field=models.DecimalField(decimal_places=2, default=25, help_text='Annual vesting percent used for annualized equity', max_digits=5),
        ),
    ]

