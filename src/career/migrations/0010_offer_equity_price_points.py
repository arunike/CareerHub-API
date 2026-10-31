from django.db import migrations, models

TABLE = 'career_offer'
COLUMN = 'equity_price_points'


def add_column(apps, schema_editor):
    """Raw ADD COLUMN: the generated AddField emits an ALTER COLUMN DROP DEFAULT that Nile rejects."""
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(
            f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {COLUMN} jsonb NOT NULL DEFAULT '[]'::jsonb"
        )
    else:
        # sqlite rejects IF NOT EXISTS on ADD COLUMN, and a fresh build never has the column.
        schema_editor.execute(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} text NOT NULL DEFAULT '[]'")


def drop_column(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(f'ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {COLUMN}')


class Migration(migrations.Migration):
    dependencies = [('career', '0009_offer_equity_vest_overrides')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_column, drop_column)],
            state_operations=[
                migrations.AddField(
                    model_name='offer',
                    name='equity_price_points',
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text='Prices typed for a grant with no ticker, [{"date": "2026-07-01", "price": "125.00"}]',
                    ),
                )
            ],
        )
    ]
