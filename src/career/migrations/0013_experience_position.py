from django.db import migrations, models


def add_experience_position_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor not in {'postgresql', 'sqlite'}:
        return

    Experience = apps.get_model('career', 'Experience')
    table_name = Experience._meta.db_table
    with connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

    if 'position' in existing_columns:
        return

    quote_name = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f'ALTER TABLE {quote_name(table_name)} '
            f"ADD COLUMN {quote_name('position')} integer DEFAULT 0 NULL"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0012_experience_level'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_experience_position_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='experience',
                    name='position',
                    field=models.PositiveIntegerField(
                        blank=True,
                        default=0,
                        help_text='Custom display order position',
                        null=True,
                    ),
                ),
            ],
        ),
    ]
