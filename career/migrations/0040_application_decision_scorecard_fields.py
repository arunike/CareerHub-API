import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0039_alter_document_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="brand_score",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Manual company brand score from 1 to 5",
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(5),
                ],
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="day_one_gc",
            field=models.CharField(
                choices=[
                    ("UNKNOWN", "Unknown"),
                    ("YES", "Yes"),
                    ("NO", "No"),
                    ("NOT_APPLICABLE", "Not applicable"),
                ],
                default="UNKNOWN",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="growth_score",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Manual growth score from 1 to 5",
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(5),
                ],
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="team_score",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Manual manager/team score from 1 to 5",
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(5),
                ],
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="visa_sponsorship",
            field=models.CharField(
                choices=[
                    ("UNKNOWN", "Unknown"),
                    ("NOT_NEEDED", "Not needed"),
                    ("AVAILABLE", "Sponsorship available"),
                    ("TRANSFER_ONLY", "Transfer only"),
                    ("NOT_AVAILABLE", "No sponsorship"),
                ],
                default="UNKNOWN",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="work_life_score",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Manual work-life balance score from 1 to 5",
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(5),
                ],
            ),
        ),
    ]
