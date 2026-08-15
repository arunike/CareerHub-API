from django.db import migrations, models


def add_default_holiday_color_if_missing(apps, schema_editor):
    UserSettings = apps.get_model("availability", "UserSettings")
    table_name = UserSettings._meta.db_table
    column_name = "default_holiday_color"

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

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} varchar(32) "
            "NOT NULL DEFAULT 'green'"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0008_usersettings_nav_item_order"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_default_holiday_color_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="usersettings",
                    name="default_holiday_color",
                    field=models.CharField(
                        default="green",
                        help_text="Colour for time off that has no holiday tab (the My Time Off bucket)",
                        max_length=32,
                    ),
                ),
            ],
        ),
    ]
