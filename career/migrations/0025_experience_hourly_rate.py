from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0024_experience_offer'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='hourly_rate',
            field=models.DecimalField(
                blank=True, null=True,
                max_digits=8, decimal_places=2,
                help_text='Hourly pay rate (for internships)',
            ),
        ),
    ]
