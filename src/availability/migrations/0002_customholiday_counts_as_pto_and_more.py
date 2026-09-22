from django.db import migrations, models

TABLE = 'availability_customholiday'


def add_columns(apps, schema_editor):
    """Raw ADD COLUMN: the generated AddField emits an ALTER COLUMN DROP DEFAULT that Nile rejects."""
    postgres = schema_editor.connection.vendor == 'postgresql'
    exists = 'IF NOT EXISTS ' if postgres else ''
    schema_editor.execute(
        f'ALTER TABLE {TABLE} ADD COLUMN {exists}counts_as_pto boolean NOT NULL DEFAULT true'
    )
    schema_editor.execute(f'ALTER TABLE {TABLE} ADD COLUMN {exists}pto_experience_id integer NULL')


def drop_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for column in ('counts_as_pto', 'pto_experience_id'):
        schema_editor.execute(f'ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [('availability', '0001_initial')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_columns, drop_columns)],
            state_operations=[
                migrations.AddField(
                    model_name='customholiday',
                    name='counts_as_pto',
                    field=models.BooleanField(
                        default=True,
                        help_text='Off for a day that is marked but not actually taken as leave',
                    ),
                ),
                migrations.AddField(
                    model_name='customholiday',
                    name='pto_experience_id',
                    field=models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        help_text='Role this day is charged to. Null falls back to whichever role was running that day.',
                    ),
                ),
            ],
        )
    ]
