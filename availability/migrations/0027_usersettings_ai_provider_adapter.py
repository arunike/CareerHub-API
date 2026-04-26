from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0026_usersettings_application_stages"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="ai_provider_adapter",
            field=models.CharField(
                choices=[
                    ("claude", "Claude"),
                    ("gemini", "Gemini"),
                    ("openai", "OpenAI"),
                    ("openrouter", "OpenRouter"),
                ],
                default="openai",
                help_text="Provider protocol used by the authenticated user's BYOK configuration.",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="usersettings",
            name="ai_provider_adapter",
            field=models.CharField(
                choices=[
                    ("claude", "Claude"),
                    ("gemini", "Gemini"),
                    ("openai", "OpenAI"),
                    ("openrouter", "OpenRouter"),
                ],
                default="gemini",
                help_text="Provider protocol used by the authenticated user's BYOK configuration.",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="usersettings",
            name="ai_provider_endpoint",
            field=models.URLField(
                blank=True,
                default="https://generativelanguage.googleapis.com/v1beta",
                help_text="Stored AI provider endpoint for the authenticated user's BYOK configuration.",
                max_length=500,
            ),
        ),
        migrations.AlterField(
            model_name="usersettings",
            name="ai_provider_model",
            field=models.CharField(
                blank=True,
                default="gemini-3-flash-preview",
                help_text="Stored AI provider model name for the authenticated user's BYOK configuration.",
                max_length=255,
            ),
        ),
    ]
