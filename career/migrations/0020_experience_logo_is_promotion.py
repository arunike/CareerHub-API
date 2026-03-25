from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0019_experience_skills"),
    ]

    operations = [
        migrations.AddField(
            model_name="experience",
            name="logo",
            field=models.ImageField(blank=True, null=True, upload_to="experience_logos/"),
        ),
        migrations.AddField(
            model_name="experience",
            name="is_promotion",
            field=models.BooleanField(
                default=False,
                help_text="Groups this role with the previous role at the same company as a promotion",
            ),
        ),
    ]
