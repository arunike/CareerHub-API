from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('career', '0052_timeline_reminder_note_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiartifact',
            name='source_experience',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ai_artifacts',
                to='career.experience',
            ),
        ),
        migrations.AlterField(
            model_name='aiartifact',
            name='artifact_type',
            field=models.CharField(
                choices=[
                    ('JD_REPORT', 'JD Report'),
                    ('COVER_LETTER', 'Cover Letter'),
                    ('NEGOTIATION_RESULT', 'Negotiation Result'),
                    ('PROMOTION_REVIEW', 'Promotion Review'),
                ],
                max_length=40,
            ),
        ),
    ]
