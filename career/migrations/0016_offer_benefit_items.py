from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0015_offer_holiday_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='benefit_items',
            field=models.JSONField(blank=True, default=list, help_text='Benefit item breakdown used to derive annual benefits value'),
        ),
    ]

