from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0014_application_tax_and_rent_overrides'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='holiday_days',
            field=models.IntegerField(default=11),
        ),
    ]

