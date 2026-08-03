from django.db import migrations


def drop_reminder_columns(apps, schema_editor):
    connection = schema_editor.connection
    table_name = 'career_applicationtimelineentry'
    with connection.cursor() as cursor:
        existing = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }
    quote_name = connection.ops.quote_name
    with connection.cursor() as cursor:
        for column_name in ('reminder_date', 'reminder_note'):
            if column_name in existing:
                cursor.execute(
                    f'ALTER TABLE {quote_name(table_name)} DROP COLUMN {quote_name(column_name)}'
                )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0017_offer_equity_refresh_and_offer_letter_type"),
    ]

    operations = [
        migrations.RunPython(drop_reminder_columns, migrations.RunPython.noop),
    ]
