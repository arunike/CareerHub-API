from django.db import migrations, models


def add_column(apps, schema_editor):
    """Raw ADD COLUMN: the generated AddField emits an ALTER COLUMN DROP DEFAULT that Nile rejects."""
    table = 'career_incomeyear'
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(
            f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS pay_lag_days smallint NOT NULL DEFAULT 0'
        )
    else:
        # sqlite rejects IF NOT EXISTS on ADD COLUMN, and a fresh build never has the column.
        schema_editor.execute(f'ALTER TABLE {table} ADD COLUMN pay_lag_days smallint NOT NULL DEFAULT 0')


def drop_column(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('ALTER TABLE career_incomeyear DROP COLUMN IF EXISTS pay_lag_days')


class Migration(migrations.Migration):
    dependencies = [('career', '0001_initial')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_column, drop_column)],
            state_operations=[
                migrations.AddField(
                    model_name='incomeyear',
                    name='pay_lag_days',
                    field=models.PositiveSmallIntegerField(
                        default=0,
                        help_text='Days between a pay period ending and its paycheck, read off a payslip; 0 means paid on the last day of the period',
                    ),
                )
            ],
        )
    ]
