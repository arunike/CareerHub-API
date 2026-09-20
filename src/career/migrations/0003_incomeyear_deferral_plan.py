from django.db import migrations, models


def add_column(apps, schema_editor):
    """Raw ADD COLUMN: the generated AddField emits an ALTER COLUMN DROP DEFAULT that Nile rejects."""
    table = 'career_incomeyear'
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS deferral_plan jsonb NOT NULL DEFAULT '{{}}'::jsonb"
        )
    else:
        # sqlite rejects IF NOT EXISTS on ADD COLUMN, and a fresh build never has the column.
        schema_editor.execute(f"ALTER TABLE {table} ADD COLUMN deferral_plan text NOT NULL DEFAULT '{{}}'")


def drop_column(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('ALTER TABLE career_incomeyear DROP COLUMN IF EXISTS deferral_plan')


class Migration(migrations.Migration):
    dependencies = [('career', '0002_incomeyear_pay_lag_days')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_column, drop_column)],
            state_operations=[
                migrations.AddField(
                    model_name='incomeyear',
                    name='deferral_plan',
                    field=models.JSONField(
                        blank=True,
                        default=dict,
                        help_text='{steps: [{id, effectiveDate, pretaxPercent, rothPercent}], escalation: {enabled, percentPerYear, capPercent}} 401(k) rate changes by date, plus annual auto-escalation',
                    ),
                )
            ],
        )
    ]
