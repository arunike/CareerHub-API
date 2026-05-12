from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("career", "0050_googlesheetsyncconfig_overwrite_strategies_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="source_removed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="application",
            name="source_removed_delete_after",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="application",
            name="source_removed_previous_status",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="googlesheetsyncconfig",
            name="missing_row_strategy",
            field=models.CharField(
                choices=[
                    ("IGNORE", "Ignore missing rows"),
                    ("ARCHIVE_THEN_DELETE", "Archive then delete missing rows"),
                ],
                default="ARCHIVE_THEN_DELETE",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="googlesheetsyncconfig",
            name="missing_row_delete_after_days",
            field=models.PositiveSmallIntegerField(
                default=30,
                validators=[MinValueValidator(1), MaxValueValidator(365)],
            ),
        ),
    ]
