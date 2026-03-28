from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0025_experience_hourly_rate'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='base_salary',
            field=models.DecimalField(blank=True, null=True, max_digits=12, decimal_places=2, help_text='Annual base salary'),
        ),
        migrations.AddField(
            model_name='experience',
            name='bonus',
            field=models.DecimalField(blank=True, null=True, max_digits=12, decimal_places=2, help_text='Annual target bonus'),
        ),
        migrations.AddField(
            model_name='experience',
            name='equity',
            field=models.DecimalField(blank=True, null=True, max_digits=12, decimal_places=2, help_text='Annualized equity value'),
        ),
    ]
