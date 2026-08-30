from django.db import migrations, models


def backfill(apps, schema_editor):
    """Read the boolean this column replaces, so nobody's carve-out is silently reset."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'career_incomeyear'"
            " AND column_name = 'exclude_allowances_from_deferral_base'"
        )
        old_column_exists = cursor.fetchone() is not None

    if not old_column_exists:
        # 0036 has already dropped it, or this is a rebuild; ALL is the field's own default.
        schema_editor.execute(
            "UPDATE career_incomeyear SET deferral_base = 'ALL' WHERE deferral_base IS NULL"
        )
        return

    schema_editor.execute(
        """
        UPDATE career_incomeyear
        SET deferral_base = CASE
            WHEN exclude_allowances_from_deferral_base THEN 'NO_ALLOWANCES'
            ELSE 'ALL'
        END
        WHERE deferral_base IS NULL
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0034_remove_aiartifact_source_offer_delete_taxprofile"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Nile refuses the DROP DEFAULT Django emits after ADD COLUMN ... DEFAULT ... NOT NULL,
            # so the column is added bare and nullable and the default lives in Django only.
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE career_incomeyear "
                    "ADD COLUMN IF NOT EXISTS deferral_base varchar(20);",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # The retired column is NOT NULL with no default, and the new code no longer
                # writes it — so between this migration and 0036 every insert would fail.
                migrations.RunSQL(
                    "ALTER TABLE career_incomeyear "
                    "ALTER COLUMN exclude_allowances_from_deferral_base DROP NOT NULL;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # Every ALTER lands before this UPDATE: an ALTER afterwards in the same
                # transaction is refused for pending trigger events. Dropping the old column
                # therefore waits for 0036.
                migrations.RunPython(backfill, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="incomeyear",
                    name="deferral_base",
                    field=models.CharField(
                        blank=True,
                        default="ALL",
                        help_text=(
                            "Pay the 401(k) defers and matches on: ALL, NO_ALLOWANCES or "
                            "SALARY_ONLY"
                        ),
                        max_length=20,
                        null=True,
                    ),
                ),
            ],
        ),
    ]
