from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0028_experience_team_history'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='is_pinned',
            field=models.BooleanField(default=False, help_text='Pinned experiences appear at the top of the list'),
        ),
    ]
