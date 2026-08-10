from django.db import migrations, models


def add_usersettings_nav_item_order_if_missing(apps, schema_editor):
    UserSettings = apps.get_model("availability", "UserSettings")
    table_name = UserSettings._meta.db_table
    column_name = "nav_item_order"

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
    column_type = "jsonb" if schema_editor.connection.vendor == "postgresql" else "text"

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {column_type}")
        cursor.execute(
            f"UPDATE {quoted_table} SET {quoted_column} = %s WHERE {quoted_column} IS NULL",
            ["[]"],
        )


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0007_event_override_date_event_span_parent"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_usersettings_nav_item_order_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="usersettings",
                    name="nav_item_order",
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Ordered list of sidebar route keys; keys absent from the list keep their built-in order",
                    ),
                ),
            ],
        ),
    ]
