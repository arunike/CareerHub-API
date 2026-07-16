from django.db import migrations, models


LEGACY_COLUMN_DEFINITIONS = {
    "counteroffer_history": {
        "postgresql": "jsonb DEFAULT '[]'::jsonb NOT NULL",
        "sqlite": "text DEFAULT '[]' NOT NULL",
    },
    "deadline": {
        "postgresql": "date NULL",
        "sqlite": "date NULL",
    },
    "final_decision_reasoning": {
        "postgresql": "text DEFAULT '' NOT NULL",
        "sqlite": "text DEFAULT '' NOT NULL",
    },
    "final_decision_status": {
        "postgresql": "varchar(20) DEFAULT 'PENDING' NOT NULL",
        "sqlite": "varchar(20) DEFAULT 'PENDING' NOT NULL",
    },
    "negotiation_rounds": {
        "postgresql": "jsonb DEFAULT '[]'::jsonb NOT NULL",
        "sqlite": "text DEFAULT '[]' NOT NULL",
    },
    "risk_notes": {
        "postgresql": "text DEFAULT '' NOT NULL",
        "sqlite": "text DEFAULT '' NOT NULL",
    },
}


def add_legacy_offer_columns_if_missing(apps, schema_editor):
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

    quote_name = connection.ops.quote_name
    quoted_table = quote_name(table_name)
    with connection.cursor() as cursor:
        for column_name, definitions in LEGACY_COLUMN_DEFINITIONS.items():
            if column_name in existing_columns:
                continue
            cursor.execute(
                f"ALTER TABLE {quoted_table} ADD COLUMN {quote_name(column_name)} "
                f"{definitions[connection.vendor]}"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0003_recalculate_timeline_stage_order"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_legacy_offer_columns_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="offer",
                    name="counteroffer_history",
                    field=models.JSONField(blank=True, default=list),
                ),
                migrations.AddField(
                    model_name="offer",
                    name="deadline",
                    field=models.DateField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="offer",
                    name="final_decision_reasoning",
                    field=models.TextField(blank=True),
                ),
                migrations.AddField(
                    model_name="offer",
                    name="final_decision_status",
                    field=models.CharField(default="PENDING", max_length=20),
                ),
                migrations.AddField(
                    model_name="offer",
                    name="negotiation_rounds",
                    field=models.JSONField(blank=True, default=list),
                ),
                migrations.AddField(
                    model_name="offer",
                    name="risk_notes",
                    field=models.TextField(blank=True),
                ),
            ],
        ),
    ]
