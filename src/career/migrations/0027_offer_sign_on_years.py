from django.db import migrations, models

CHECK_NAME = "career_offer_sign_on_years_positive"


def add_sign_on_years(_apps, schema_editor):
    """Add sign_on_years.

    The generated AddField emits "ALTER COLUMN ... DROP DEFAULT" after the column, which the
    production Postgres rejects. Keeping the server-side default and adding the positive
    check as its own ADD CONSTRAINT is accepted; Django never relies on the default itself.
    """
    if schema_editor.connection.vendor != "postgresql":
        schema_editor.execute(
            'ALTER TABLE "career_offer" ADD COLUMN "sign_on_years" smallint NOT NULL '
            'DEFAULT 1 CHECK ("sign_on_years" >= 0);'
        )
        return

    schema_editor.execute(
        'ALTER TABLE "career_offer" ADD COLUMN "sign_on_years" smallint NOT NULL DEFAULT 1;'
    )
    schema_editor.execute(
        f'ALTER TABLE "career_offer" ADD CONSTRAINT "{CHECK_NAME}" '
        'CHECK ("sign_on_years" >= 0);'
    )


def drop_sign_on_years(_apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            f'ALTER TABLE "career_offer" DROP CONSTRAINT IF EXISTS "{CHECK_NAME}";'
        )
    schema_editor.execute('ALTER TABLE "career_offer" DROP COLUMN "sign_on_years";')


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0026_remove_contactcontext_notes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="offer",
                    name="sign_on_years",
                    field=models.PositiveSmallIntegerField(default=1),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_sign_on_years, drop_sign_on_years),
            ],
        ),
    ]
