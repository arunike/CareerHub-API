from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0038_alter_experience_logo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="file",
            field=models.URLField(blank=True, max_length=2048, null=True),
        ),
    ]
