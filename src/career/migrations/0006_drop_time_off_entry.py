from django.db import migrations


def drop_table(apps, schema_editor):
    """Raw DROP TABLE: the generated DeleteModel emits the SET CONSTRAINTS Nile refuses."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('DROP TABLE IF EXISTS career_timeoffentry')


def noop(apps, schema_editor):
    """The table held no data; a rebuild that needs it can replay 0005."""


class Migration(migrations.Migration):
    dependencies = [('career', '0005_offer_pto_rollover_expires_month_and_more')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(drop_table, noop)],
            state_operations=[migrations.DeleteModel(name='TimeOffEntry')],
        )
    ]
