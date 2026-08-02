from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0016_remove_offer_counteroffer_history"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "career_offer" '
                        'ADD COLUMN "annual_refresh_value" numeric(12, 2) DEFAULT 0 NOT NULL;'
                    ),
                    reverse_sql='ALTER TABLE "career_offer" DROP COLUMN "annual_refresh_value";',
                ),
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "career_offer" '
                        'ADD COLUMN "refresh_starts_year" smallint DEFAULT 2 NOT NULL;'
                    ),
                    reverse_sql='ALTER TABLE "career_offer" DROP COLUMN "refresh_starts_year";',
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="offer",
                    name="annual_refresh_value",
                    field=models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text=(
                            "Optional annual equity refresh grant value. "
                            "0 disables refresh modelling."
                        ),
                        max_digits=12,
                    ),
                ),
                migrations.AddField(
                    model_name="offer",
                    name="refresh_starts_year",
                    field=models.SmallIntegerField(
                        default=2,
                        help_text=(
                            "First year a refresh grant is issued. "
                            "Refreshes vest evenly over four years."
                        ),
                    ),
                ),
            ],
        ),
        # Choices-only change, so Django emits no SQL for this one.
        migrations.AlterField(
            model_name="document",
            name="document_type",
            field=models.CharField(
                choices=[
                    ("RESUME", "Resume"),
                    ("COVER_LETTER", "Cover Letter"),
                    ("OFFER_LETTER", "Offer Letter"),
                    ("PORTFOLIO", "Portfolio"),
                    ("OTHER", "Other"),
                ],
                default="RESUME",
                max_length=20,
            ),
        ),
    ]
