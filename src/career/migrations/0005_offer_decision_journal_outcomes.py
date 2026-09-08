from django.db import migrations, models


def _is_postgres(schema_editor):
    return schema_editor.connection.vendor == 'postgresql'


def add_criteria(apps, schema_editor):
    """Written by hand: Django's AddField emits the ALTER COLUMN ... DROP DEFAULT Nile rejects."""
    if _is_postgres(schema_editor):
        schema_editor.execute(
            "ALTER TABLE career_offerdecisionjournal "
            "ADD COLUMN IF NOT EXISTS criteria jsonb NOT NULL DEFAULT '[]'::jsonb"
        )
    else:
        # sqlite has no IF NOT EXISTS on ADD COLUMN, and stores JSON as text.
        schema_editor.execute(
            "ALTER TABLE career_offerdecisionjournal "
            "ADD COLUMN criteria text NOT NULL DEFAULT '[]'"
        )


def drop_criteria(apps, schema_editor):
    schema_editor.execute(
        "ALTER TABLE career_offerdecisionjournal DROP COLUMN IF EXISTS criteria"
        if _is_postgres(schema_editor)
        else "ALTER TABLE career_offerdecisionjournal DROP COLUMN criteria"
    )


def concerns_to_json(apps, schema_editor):
    """Replaced rather than cast: the column is empty, so a USING clause would buy nothing."""
    if not _is_postgres(schema_editor):
        return
    schema_editor.execute("ALTER TABLE career_offerdecisionjournal DROP COLUMN IF EXISTS concerns")
    schema_editor.execute(
        "ALTER TABLE career_offerdecisionjournal "
        "ADD COLUMN concerns jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def concerns_to_text(apps, schema_editor):
    if not _is_postgres(schema_editor):
        return
    schema_editor.execute("ALTER TABLE career_offerdecisionjournal DROP COLUMN IF EXISTS concerns")
    schema_editor.execute(
        "ALTER TABLE career_offerdecisionjournal ADD COLUMN concerns text NOT NULL DEFAULT ''"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0004_offer_decision_journal_drop_confidence"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_criteria, drop_criteria),
                migrations.RunPython(concerns_to_json, concerns_to_text),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="offerdecisionjournal",
                    name="criteria",
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Scorecard category keys that drove the call, e.g. ['financial', 'trajectory']",
                    ),
                ),
                migrations.AlterField(
                    model_name="offerdecisionjournal",
                    name="concerns",
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text="[{id, text, outcome}] where outcome is REAL, AVOIDED, UNCLEAR or null",
                    ),
                ),
                migrations.AlterField(
                    model_name="offerdecisionjournal",
                    name="reviews",
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text="[{milestone, completed_on, verdict, notes, criteria_verdicts}]",
                    ),
                ),
            ],
        ),
    ]
