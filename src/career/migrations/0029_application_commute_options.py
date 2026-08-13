from django.db import migrations, models

# A generated AddField with a default emits "ALTER COLUMN ... DROP DEFAULT", which the
# production Postgres rejects, so the column is added with its default left in place.


def add_commute_options(_apps, schema_editor):
    schema_editor.execute(
        'ALTER TABLE "career_application" ADD COLUMN "commute_options" jsonb NOT NULL '
        "DEFAULT '[]'::jsonb;"
        if schema_editor.connection.vendor == "postgresql"
        else 'ALTER TABLE "career_application" ADD COLUMN "commute_options" text NOT NULL '
        "DEFAULT '[]';"
    )


def drop_commute_options(_apps, schema_editor):
    schema_editor.execute('ALTER TABLE "career_application" DROP COLUMN "commute_options";')


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0028_remove_offer_sign_on_years_offer_sign_on_schedule"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="application",
                    name="commute_options",
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Per-mode commute entries used for time and cost comparison",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_commute_options, drop_commute_options),
            ],
        ),
    ]
