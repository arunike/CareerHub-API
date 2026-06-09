from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('career', '0053_promotion_review_ai_artifact'),
    ]

    operations = [
        migrations.CreateModel(
            name='AIArtifactGenerationJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('PROMOTION_REVIEW', 'Promotion Review')], max_length=40)),
                ('status', models.CharField(choices=[('QUEUED', 'Queued'), ('RUNNING', 'Running'), ('SUCCEEDED', 'Succeeded'), ('FAILED', 'Failed')], default='QUEUED', max_length=20)),
                ('input_payload', models.JSONField(blank=True, default=dict)),
                ('result_payload', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('artifact', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='generation_jobs', to='career.aiartifact')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ai_artifact_generation_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
