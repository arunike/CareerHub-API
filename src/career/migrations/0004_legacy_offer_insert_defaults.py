from django.db import migrations


LEGACY_COLUMN_DEFAULTS = {
    "counteroffer_history": "'[]'::jsonb",
    "final_decision_reasoning": "''",
    "final_decision_status": "'PENDING'",
    "negotiation_rounds": "'[]'::jsonb",
    "risk_notes": "''",
}


def set_legacy_offer_insert_defaults(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return

    Offer = apps.get_model("career", "Offer")
    table_name = Offer._meta.db_table

    with connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

    quote_name = connection.ops.quote_name
    quoted_table = quote_name(table_name)
    with connection.cursor() as cursor:
        for column_name, sql_default in LEGACY_COLUMN_DEFAULTS.items():
            if column_name not in existing_columns:
                continue
            cursor.execute(
                f"ALTER TABLE {quoted_table} "
                f"ALTER COLUMN {quote_name(column_name)} SET DEFAULT {sql_default}"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0003_recalculate_timeline_stage_order"),
    ]

    operations = [
        migrations.RunPython(
            set_legacy_offer_insert_defaults,
            migrations.RunPython.noop,
        ),
    ]
