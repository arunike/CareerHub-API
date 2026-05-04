from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0011_backfill_document_current'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='rto_days_per_week',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
