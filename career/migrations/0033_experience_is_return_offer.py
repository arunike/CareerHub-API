from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0032_experience_schedule_phases'),
    ]

    operations = [
        migrations.AddField(
            model_name='experience',
            name='is_return_offer',
            field=models.BooleanField(default=False, help_text='Marks this role as having originated from a return internship offer'),
        ),
    ]
