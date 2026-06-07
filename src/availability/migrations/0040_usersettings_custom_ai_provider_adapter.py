from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('availability', '0039_public_booking_controls'),
    ]

    operations = [
        migrations.AlterField(
            model_name='usersettings',
            name='ai_provider_adapter',
            field=models.CharField(
                choices=[
                    ('claude', 'Claude'),
                    ('gemini', 'Gemini'),
                    ('openai', 'OpenAI'),
                    ('openrouter', 'OpenRouter'),
                    ('custom', 'Custom'),
                ],
                default='gemini',
                help_text="Provider protocol used by the authenticated user's BYOK configuration.",
                max_length=32,
            ),
        ),
    ]
