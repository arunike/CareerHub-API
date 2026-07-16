from django.db import migrations, models


def add_sick_leave_days_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor not in {"postgresql", "sqlite"}:
        return

    Offer = apps.get_model("career", "Offer")
    table_name = Offer._meta.db_table

    with connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

    if "sick_leave_days" in existing_columns:
        return

    quote_name = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {quote_name(table_name)} "
            f"ADD COLUMN {quote_name('sick_leave_days')} integer DEFAULT 0 NOT NULL"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0005_offer_equity_liquidity"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_sick_leave_days_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="offer",
                    name="sick_leave_days",
                    field=models.IntegerField(default=0),
                ),
            ],
        ),
    ]
