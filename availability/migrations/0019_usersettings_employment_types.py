from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0018_customholiday_holiday_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='usersettings',
            name='employment_types',
            field=models.JSONField(blank=True, default=list, help_text='Custom employment type definitions [{value, label, color}]'),
        ),
    ]
