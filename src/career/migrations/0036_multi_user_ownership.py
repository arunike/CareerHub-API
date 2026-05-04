from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('career', '0035_application_office_location'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='applications', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='company',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='companies', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='document',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='documents', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='experience',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='experiences', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='task',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tasks', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddConstraint(
            model_name='company',
            constraint=models.UniqueConstraint(fields=('user', 'name'), name='unique_company_per_user'),
        ),
    ]
