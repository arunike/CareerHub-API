from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0019_usersettings_employment_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='customholiday',
            name='tab',
            field=models.CharField(blank=True, help_text='Custom tab id this holiday belongs to', max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='usersettings',
            name='holiday_tabs',
            field=models.JSONField(blank=True, default=list, help_text='User-defined holiday tab definitions [{id, name}]'),
        ),
    ]
