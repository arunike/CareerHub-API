from django.db import migrations, models


def add_application_level_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor not in {'postgresql', 'sqlite'}:
        return

    Application = apps.get_model('career', 'Application')
    table_name = Application._meta.db_table
    with connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

    if 'level' in existing_columns:
        return

    quote_name = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f'ALTER TABLE {quote_name(table_name)} '
            f"ADD COLUMN {quote_name('level')} varchar(50) DEFAULT '' NOT NULL"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0009_recalculate_canonical_timeline_order'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_application_level_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='application',
                    name='level',
                    field=models.CharField(
                        blank=True,
                        default='',
                        help_text='Job level or band, e.g. L5, Senior, Staff, IC3',
                        max_length=50,
                    ),
                ),
            ],
        ),
    ]
