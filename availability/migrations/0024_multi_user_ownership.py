from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('availability', '0023_usersettings_work_time_ranges'),
    ]

    operations = [
        migrations.AddField(
            model_name='availabilityoverride',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='availability_overrides', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='availabilitysetting',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='availability_key_settings', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='customholiday',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='custom_holidays', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='event',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='events', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='eventcategory',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='event_categories', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='sharelink',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='share_links', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='usersettings',
            name='user',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='availability_settings_profile', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='availabilityoverride',
            name='date',
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name='availabilitysetting',
            name='key',
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name='eventcategory',
            name='name',
            field=models.CharField(max_length=50),
        ),
        migrations.AddConstraint(
            model_name='availabilityoverride',
            constraint=models.UniqueConstraint(fields=('user', 'date'), name='unique_availability_override_per_user'),
        ),
        migrations.AddConstraint(
            model_name='availabilitysetting',
            constraint=models.UniqueConstraint(fields=('user', 'key'), name='unique_availability_setting_per_user'),
        ),
        migrations.AddConstraint(
            model_name='eventcategory',
            constraint=models.UniqueConstraint(fields=('user', 'name'), name='unique_event_category_per_user'),
        ),
    ]
