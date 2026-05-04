from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0020_experience_logo_is_promotion'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='is_locked',
            # null=True avoids SQLite NOT NULL constraint issues on ALTER TABLE ADD COLUMN
            field=models.BooleanField(default=False, null=True, blank=True, help_text='Locked roles cannot be edited or deleted'),
        ),
    ]
