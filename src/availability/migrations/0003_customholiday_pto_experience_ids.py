from django.db import migrations, models

TABLE = 'availability_customholiday'


def swap_columns(apps, schema_editor):
    """The single-id column shipped hours ago and holds nothing, so it is replaced outright."""
    postgres = schema_editor.connection.vendor == 'postgresql'
    exists = 'IF NOT EXISTS ' if postgres else ''
    schema_editor.execute(
        f"ALTER TABLE {TABLE} ADD COLUMN {exists}pto_experience_ids jsonb NOT NULL DEFAULT '[]'::jsonb"
        if postgres
        else f"ALTER TABLE {TABLE} ADD COLUMN pto_experience_ids text NOT NULL DEFAULT '[]'"
    )
    if postgres:
        schema_editor.execute(f'ALTER TABLE {TABLE} DROP COLUMN IF EXISTS pto_experience_id')


def restore_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(
        f'ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS pto_experience_id integer NULL'
    )
    schema_editor.execute(f'ALTER TABLE {TABLE} DROP COLUMN IF EXISTS pto_experience_ids')


class Migration(migrations.Migration):
    dependencies = [('availability', '0002_customholiday_counts_as_pto_and_more')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(swap_columns, restore_columns)],
            state_operations=[
                migrations.RemoveField(model_name='customholiday', name='pto_experience_id'),
                migrations.AddField(
                    model_name='customholiday',
                    name='pto_experience_ids',
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text='Roles this day is charged to. Empty falls back to whichever roles were running that day.',
                    ),
                ),
            ],
        )
    ]
