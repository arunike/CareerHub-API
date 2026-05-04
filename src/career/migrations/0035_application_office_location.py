from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0034_offer_is_unlimited_pto'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='office_location',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
