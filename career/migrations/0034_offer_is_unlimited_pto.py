from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0033_experience_is_return_offer'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='is_unlimited_pto',
            field=models.BooleanField(default=False, help_text='Offer includes unlimited PTO'),
        ),
    ]
