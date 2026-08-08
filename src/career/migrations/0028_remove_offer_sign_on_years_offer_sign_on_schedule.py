from django.db import migrations, models

CHECK_NAME = "career_offer_sign_on_years_positive"


def add_sign_on_schedule(_apps, schema_editor):
    """Add sign_on_schedule and drop the superseded sign_on_years.

    A generated AddField with a default emits "ALTER COLUMN ... DROP DEFAULT", which the
    production Postgres rejects, so the column is added with its default left in place.
    sign_on_years only ever held its default of 1, so nothing needs migrating across.
    """
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            f'ALTER TABLE "career_offer" DROP CONSTRAINT IF EXISTS "{CHECK_NAME}";'
        )
    schema_editor.execute('ALTER TABLE "career_offer" DROP COLUMN "sign_on_years";')
    schema_editor.execute(
        'ALTER TABLE "career_offer" ADD COLUMN "sign_on_schedule" jsonb NOT NULL '
        "DEFAULT '[]'::jsonb;"
        if schema_editor.connection.vendor == "postgresql"
        else 'ALTER TABLE "career_offer" ADD COLUMN "sign_on_schedule" text NOT NULL '
        "DEFAULT '[]';"
    )


def drop_sign_on_schedule(_apps, schema_editor):
    schema_editor.execute('ALTER TABLE "career_offer" DROP COLUMN "sign_on_schedule";')
    schema_editor.execute(
        'ALTER TABLE "career_offer" ADD COLUMN "sign_on_years" smallint NOT NULL DEFAULT 1;'
    )
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            f'ALTER TABLE "career_offer" ADD CONSTRAINT "{CHECK_NAME}" '
            'CHECK ("sign_on_years" >= 0);'
        )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0027_offer_sign_on_years"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="offer", name="sign_on_years"),
                migrations.AddField(
                    model_name="offer",
                    name="sign_on_schedule",
                    field=models.JSONField(blank=True, default=list),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_sign_on_schedule, drop_sign_on_schedule),
            ],
        ),
    ]
