from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0040_usersettings_custom_ai_provider_adapter"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="is_locked",
            field=models.BooleanField(
                default=False,
                help_text="Locked settings cannot be edited until unlocked",
            ),
        ),
    ]
