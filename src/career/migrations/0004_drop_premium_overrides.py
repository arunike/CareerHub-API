from django.db import migrations

TABLE = 'career_incomeyear'
COLUMNS = [
    'medical_premium_override',
    'dental_premium_override',
    'vision_premium_override',
    'dependent_premium_override',
]


def drop_columns(apps, schema_editor):
    """Raw DROP COLUMN: the generated RemoveField emits statements Nile refuses."""
    if schema_editor.connection.vendor != 'postgresql':
        # sqlite rejects DROP COLUMN IF EXISTS; the columns are nullable, so leaving them is inert.
        return
    for column in COLUMNS:
        schema_editor.execute(f'ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {column}')


def add_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for column in COLUMNS:
        schema_editor.execute(f'ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {column} numeric(10, 2) NULL')


class Migration(migrations.Migration):
    dependencies = [('career', '0003_incomeyear_deferral_plan')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(drop_columns, add_columns)],
            state_operations=[
                migrations.RemoveField(model_name='incomeyear', name=column) for column in COLUMNS
            ],
        )
    ]
