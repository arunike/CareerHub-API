from django.db import migrations, models


COLUMN_DEFINITIONS = {
    "postgresql": "boolean DEFAULT true NOT NULL",
    "sqlite": "bool DEFAULT 1 NOT NULL",
}


def add_sick_leave_policy_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor not in COLUMN_DEFINITIONS:
        return

    Offer = apps.get_model("career", "Offer")
    table_name = Offer._meta.db_table

    with connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

    column_name = "sick_leave_included_in_unlimited_pto"
    if column_name in existing_columns:
        return

    quote_name = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {quote_name(table_name)} "
            f"ADD COLUMN {quote_name(column_name)} {COLUMN_DEFINITIONS[connection.vendor]}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0006_offer_sick_leave_days"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_sick_leave_policy_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="offer",
                    name="sick_leave_included_in_unlimited_pto",
                    field=models.BooleanField(default=True),
                ),
            ],
        ),
    ]
