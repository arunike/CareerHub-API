from django.db import migrations, models


EQUITY_COLUMN_DEFINITIONS = {
    "equity_liquidity": {
        "postgresql": "varchar(20) DEFAULT 'LIQUID' NOT NULL",
        "sqlite": "varchar(20) DEFAULT 'LIQUID' NOT NULL",
    },
    "equity_buyback_value": {
        "postgresql": "numeric(12, 2) DEFAULT 0 NOT NULL",
        "sqlite": "decimal DEFAULT 0 NOT NULL",
    },
}


def add_equity_liquidity_columns_if_missing(apps, schema_editor):
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
        for column_name, definitions in EQUITY_COLUMN_DEFINITIONS.items():
            if column_name in existing_columns:
                continue
            cursor.execute(
                f"ALTER TABLE {quoted_table} ADD COLUMN {quote_name(column_name)} "
                f"{definitions[connection.vendor]}"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0004_legacy_offer_insert_defaults"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_equity_liquidity_columns_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="offer",
                    name="equity_buyback_value",
                    field=models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text="Annual equity value realizable through a company buyback",
                        max_digits=12,
                    ),
                ),
                migrations.AddField(
                    model_name="offer",
                    name="equity_liquidity",
                    field=models.CharField(
                        choices=[
                            ("LIQUID", "Public or Freely Tradable"),
                            ("BUYBACK", "Private with Company Buyback"),
                            ("ILLIQUID", "Private and Not Sellable"),
                        ],
                        default="LIQUID",
                        max_length=20,
                    ),
                ),
            ],
        ),
    ]
