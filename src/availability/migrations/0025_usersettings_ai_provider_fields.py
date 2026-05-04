from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0024_multi_user_ownership"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="ai_provider_api_key_encrypted",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Encrypted AI provider API key for the authenticated user.",
            ),
        ),
        migrations.AddField(
            model_name="usersettings",
            name="ai_provider_endpoint",
            field=models.URLField(
                blank=True,
                default="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                help_text="Stored AI provider endpoint for the authenticated user's BYOK configuration.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name="usersettings",
            name="ai_provider_model",
            field=models.CharField(
                blank=True,
                default="gemini-2.0-flash",
                help_text="Stored AI provider model name for the authenticated user's BYOK configuration.",
                max_length=255,
            ),
        ),
    ]
