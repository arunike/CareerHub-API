from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0021_eventcategory_is_locked'),
    ]

    operations = [
        migrations.AddField(
            model_name='usersettings',
            name='hidden_nav_items',
            field=models.JSONField(blank=True, default=list, help_text='List of nav route keys to hide from sidebar'),
        ),
    ]
