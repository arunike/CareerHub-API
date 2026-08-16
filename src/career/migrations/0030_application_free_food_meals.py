from django.db import migrations, models

# A generated AddField with a default emits "ALTER COLUMN ... DROP DEFAULT", which the
# production Postgres rejects, so the columns are added with their defaults left in place.


def add_free_food_fields(_apps, schema_editor):
    is_postgres = schema_editor.connection.vendor == "postgresql"
    schema_editor.execute(
        'ALTER TABLE "career_application" ADD COLUMN "free_food_meals" jsonb NOT NULL '
        "DEFAULT '[]'::jsonb;"
        if is_postgres
        else 'ALTER TABLE "career_application" ADD COLUMN "free_food_meals" text NOT NULL '
        "DEFAULT '[]';"
    )
    schema_editor.execute(
        'ALTER TABLE "career_application" ADD COLUMN "free_food_value_per_meal" '
        "numeric(8, 2) NULL;"
    )


def drop_free_food_fields(_apps, schema_editor):
    schema_editor.execute('ALTER TABLE "career_application" DROP COLUMN "free_food_meals";')
    schema_editor.execute(
        'ALTER TABLE "career_application" DROP COLUMN "free_food_value_per_meal";'
    )


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0029_application_commute_options"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="application",
                    name="free_food_meals",
                    field=models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Meals provided on an office day",
                    ),
                ),
                migrations.AddField(
                    model_name="application",
                    name="free_food_value_per_meal",
                    field=models.DecimalField(
                        blank=True, decimal_places=2, max_digits=8, null=True
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_free_food_fields, drop_free_food_fields),
            ],
        ),
    ]
