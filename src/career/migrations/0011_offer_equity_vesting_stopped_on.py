from django.db import migrations, models

TABLE = 'career_offer'
COLUMN = 'equity_vesting_stopped_on'


def add_column(apps, schema_editor):
    """Raw ADD COLUMN: the generated AddField emits an ALTER COLUMN DROP DEFAULT that Nile rejects."""
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(f'ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {COLUMN} date NULL')
    else:
        # sqlite rejects IF NOT EXISTS on ADD COLUMN, and a fresh build never has the column.
        schema_editor.execute(f'ALTER TABLE {TABLE} ADD COLUMN {COLUMN} date NULL')


def drop_column(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(f'ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {COLUMN}')


class Migration(migrations.Migration):
    dependencies = [('career', '0010_offer_equity_price_points')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_column, drop_column)],
            state_operations=[
                migrations.AddField(
                    model_name='offer',
                    name='equity_vesting_stopped_on',
                    field=models.DateField(
                        blank=True,
                        null=True,
                        help_text="Day the grant stopped vesting, when it is not the role's own last day",
                    ),
                )
            ],
        )
    ]
