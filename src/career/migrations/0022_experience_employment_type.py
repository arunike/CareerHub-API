from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0021_experience_is_locked'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='employment_type',
            # null=True avoids SQLite NOT NULL constraint issues on ALTER TABLE ADD COLUMN
            field=models.CharField(
                max_length=20,
                choices=[
                    ('full_time', 'Full-time'),
                    ('part_time', 'Part-time'),
                    ('internship', 'Internship'),
                    ('contract', 'Contract'),
                    ('freelance', 'Freelance'),
                ],
                default='full_time',
                null=True,
                blank=True,
            ),
        ),
    ]
