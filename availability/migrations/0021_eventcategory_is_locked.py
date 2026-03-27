from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0020_customholiday_tab_usersettings_holiday_tabs'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventcategory',
            name='is_locked',
            field=models.BooleanField(default=False),
        ),
    ]
