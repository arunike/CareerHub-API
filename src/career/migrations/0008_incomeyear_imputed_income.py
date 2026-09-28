from django.db import migrations, models

TABLE = 'career_incomeyear'
COLUMN = 'imputed_income_per_period'


def add_column(apps, schema_editor):
    """Raw ADD COLUMN: the generated AddField emits an ALTER COLUMN DROP DEFAULT that Nile rejects."""
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(
            f'ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {COLUMN} numeric(10, 2) NOT NULL DEFAULT 0'
        )
    else:
        # sqlite rejects IF NOT EXISTS on ADD COLUMN, and a fresh build never has the column.
        schema_editor.execute(
            f'ALTER TABLE {TABLE} ADD COLUMN {COLUMN} numeric(10, 2) NOT NULL DEFAULT 0'
        )


def drop_column(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(f'ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {COLUMN}')


class Migration(migrations.Migration):
    dependencies = [('career', '0007_offer_pto_accrual')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_column, drop_column)],
            state_operations=[
                migrations.AddField(
                    model_name='incomeyear',
                    name='imputed_income_per_period',
                    field=models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=10,
                        help_text='Employer-paid cover the IRS taxes as income, e.g. group term life; raises taxable gross without reaching take-home',
                    ),
                )
            ],
        )
    ]
