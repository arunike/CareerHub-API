from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0022_experience_employment_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='raise_history',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='List of raise events [{id, date, type, base_before, base_after, bonus_before, bonus_after, equity_before, equity_after, label, notes}]',
            ),
        ),
    ]
