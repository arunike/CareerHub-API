from django.db import migrations, models


def add_usersettings_is_locked_if_missing(apps, schema_editor):
    UserSettings = apps.get_model("availability", "UserSettings")
    table_name = UserSettings._meta.db_table
    column_name = "is_locked"

    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table_name
            )
        }

    if column_name in existing_columns:
        return

    quote_name = schema_editor.connection.ops.quote_name
    quoted_table = quote_name(table_name)
    quoted_column = quote_name(column_name)
    column_type = "boolean" if schema_editor.connection.vendor == "postgresql" else "bool"

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {column_type}")
        cursor.execute(
            f"UPDATE {quoted_table} SET {quoted_column} = %s WHERE {quoted_column} IS NULL",
            [False],
        )


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_usersettings_is_locked_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="usersettings",
                    name="is_locked",
                    field=models.BooleanField(
                        default=False,
                        help_text="Locked settings cannot be edited until unlocked",
                    ),
                ),
            ],
        ),
    ]
