from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('career', '0010_application_level'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='application',
            index=models.Index(
                fields=['user', 'status', 'date_applied'],
                name='career_app_ghost_idx',
            ),
        ),
    ]
