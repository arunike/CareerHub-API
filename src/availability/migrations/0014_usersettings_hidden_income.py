from django.db import migrations, models

# Column name -> the JSON literal an existing row should start with.
NEW_COLUMNS = {
    "hidden_income_roles": "[]",
    "hidden_income_years": "[]",
}


def add_hidden_income_columns_if_missing(apps, schema_editor):
    UserSettings = apps.get_model("availability", "UserSettings")
    table_name = UserSettings._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table_name
            )
        }

    quote_name = schema_editor.connection.ops.quote_name
    quoted_table = quote_name(table_name)
    column_type = "jsonb" if schema_editor.connection.vendor == "postgresql" else "text"

    missing = {
        name: empty for name, empty in NEW_COLUMNS.items() if name not in existing_columns
    }
    if not missing:
        return

    # Every ALTER first, then the backfills: an UPDATE leaves pending trigger events, and the
    # next ALTER TABLE in the same transaction is refused because of them.
    with schema_editor.connection.cursor() as cursor:
        for column_name in missing:
            # No column default: the hosted Postgres rejects the DROP DEFAULT that Django's own
            # AddField emits straight after ADD COLUMN ... DEFAULT.
            cursor.execute(
                f"ALTER TABLE {quoted_table} ADD COLUMN {quote_name(column_name)} {column_type}"
            )

    with schema_editor.connection.cursor() as cursor:
        for column_name, empty_value in missing.items():
            quoted_column = quote_name(column_name)
            cursor.execute(
                f"UPDATE {quoted_table} SET {quoted_column} = %s WHERE {quoted_column} IS NULL",
                [empty_value],
            )


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0013_usersettings_analytics_widget_order_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_hidden_income_columns_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="usersettings",
                    name="hidden_income_roles",
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text=(
                            "Income source keys to leave out of the Income page role picker"
                        ),
                    ),
                ),
                migrations.AddField(
                    model_name="usersettings",
                    name="hidden_income_years",
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Tax years to leave out of the Income page year picker",
                    ),
                ),
            ],
        ),
    ]
