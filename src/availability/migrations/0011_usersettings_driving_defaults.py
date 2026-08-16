from django.db import migrations, models

# Matches the pattern used by 0009/0010: the column is added with its default left in place,
# because a generated AddField emits an "ALTER COLUMN ... DROP DEFAULT" that this Postgres
# rejects. Guarded on the column already existing so a re-run is harmless.

COLUMNS = (
    ("default_mpg", "numeric(6, 1)", "28"),
    ("default_gas_price_per_gallon", "numeric(6, 2)", "4"),
)


def add_driving_defaults(apps, schema_editor):
    UserSettings = apps.get_model("availability", "UserSettings")
    table_name = UserSettings._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        existing = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table_name
            )
        }

    quote_name = schema_editor.connection.ops.quote_name
    quoted_table = quote_name(table_name)
    for column_name, column_type, default in COLUMNS:
        if column_name in existing:
            continue
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE {quoted_table} ADD COLUMN {quote_name(column_name)} "
                f"{column_type} NOT NULL DEFAULT {default}"
            )


def drop_driving_defaults(apps, schema_editor):
    UserSettings = apps.get_model("availability", "UserSettings")
    quote_name = schema_editor.connection.ops.quote_name
    quoted_table = quote_name(UserSettings._meta.db_table)
    for column_name, _type, _default in COLUMNS:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE {quoted_table} DROP COLUMN IF EXISTS {quote_name(column_name)}"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("availability", "0010_usersettings_federal_holiday_color"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="usersettings",
                    name="default_mpg",
                    field=models.DecimalField(
                        decimal_places=1,
                        default=28,
                        help_text="Fuel efficiency used for commute cost",
                        max_digits=6,
                    ),
                ),
                migrations.AddField(
                    model_name="usersettings",
                    name="default_gas_price_per_gallon",
                    field=models.DecimalField(
                        decimal_places=2,
                        default=4,
                        help_text="Pump price used for commute cost",
                        max_digits=6,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_driving_defaults, drop_driving_defaults),
            ],
        ),
    ]
