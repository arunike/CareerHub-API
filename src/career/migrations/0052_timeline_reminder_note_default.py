from django.db import migrations


def set_reminder_note_default(apps, schema_editor):
    table_name = 'career_applicationtimelineentry'
    column_name = 'reminder_note'
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        existing_columns = {
            column.name for column in connection.introspection.get_table_description(cursor, table_name)
        }
    if column_name not in existing_columns:
        return

    quote_name = connection.ops.quote_name
    quoted_table = quote_name(table_name)
    quoted_column = quote_name(column_name)

    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {quoted_table} SET {quoted_column} = %s WHERE {quoted_column} IS NULL", [''])
        if connection.vendor == 'postgresql':
            cursor.execute(f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} SET DEFAULT ''")


def unset_reminder_note_default(apps, schema_editor):
    table_name = 'career_applicationtimelineentry'
    column_name = 'reminder_note'
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        existing_columns = {
            column.name for column in connection.introspection.get_table_description(cursor, table_name)
        }
    if column_name not in existing_columns or connection.vendor != 'postgresql':
        return

    quote_name = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {quote_name(table_name)} ALTER COLUMN {quote_name(column_name)} DROP DEFAULT"
        )


class Migration(migrations.Migration):
    dependencies = [
        ('career', '0051_google_sheet_missing_row_archive'),
    ]

    operations = [
        migrations.RunPython(set_reminder_note_default, unset_reminder_note_default),
    ]
