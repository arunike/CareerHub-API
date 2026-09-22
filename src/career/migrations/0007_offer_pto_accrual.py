from django.db import migrations, models

TABLE = 'career_offer'


def add_columns(apps, schema_editor):
    """Raw ADD COLUMN: the generated AddField emits an ALTER COLUMN DROP DEFAULT that Nile rejects."""
    postgres = schema_editor.connection.vendor == 'postgresql'
    exists = 'IF NOT EXISTS ' if postgres else ''
    for column, ddl in (
        ('pto_accrual_days_per_year', 'smallint NOT NULL DEFAULT 0'),
        ('pto_accrual_max_days', 'smallint NOT NULL DEFAULT 0'),
        ('pto_hours_per_day', 'numeric(4, 2) NOT NULL DEFAULT 8'),
    ):
        schema_editor.execute(f'ALTER TABLE {TABLE} ADD COLUMN {exists}{column} {ddl}')


def drop_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for column in ('pto_accrual_days_per_year', 'pto_accrual_max_days', 'pto_hours_per_day'):
        schema_editor.execute(f'ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [('career', '0006_drop_time_off_entry')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_columns, drop_columns)],
            state_operations=[
                migrations.AddField(
                    model_name='offer',
                    name='pto_accrual_days_per_year',
                    field=models.PositiveSmallIntegerField(
                        default=0,
                        help_text='Extra days granted per completed year of service. 0 means the allowance never grows.',
                    ),
                ),
                migrations.AddField(
                    model_name='offer',
                    name='pto_accrual_max_days',
                    field=models.PositiveSmallIntegerField(
                        default=0, help_text='Ceiling on the days tenure can add. 0 means no ceiling.'
                    ),
                ),
                migrations.AddField(
                    model_name='offer',
                    name='pto_hours_per_day',
                    field=models.DecimalField(
                        decimal_places=2,
                        default=8,
                        max_digits=4,
                        help_text='Hours one PTO day is worth, for policies quoted in hours',
                    ),
                ),
            ],
        )
    ]
