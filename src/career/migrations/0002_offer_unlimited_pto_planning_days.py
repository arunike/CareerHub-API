from django.db import migrations, models

# A generated AddField emits "ALTER COLUMN ... DROP DEFAULT", which the production Postgres
# rejects, so the column is added by hand with its default left in place, as in the squashed 0001.


def add_planning_days(_apps, schema_editor):
    schema_editor.execute(
        'ALTER TABLE "career_offer" ADD COLUMN "unlimited_pto_planning_days" smallint NOT NULL DEFAULT 20;'
    )


def drop_planning_days(_apps, schema_editor):
    schema_editor.execute('ALTER TABLE "career_offer" DROP COLUMN "unlimited_pto_planning_days";')


class Migration(migrations.Migration):
    dependencies = [("career", "0001_initial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="offer",
                    name="unlimited_pto_planning_days",
                    field=models.PositiveSmallIntegerField(
                        db_default=20,
                        default=20,
                        help_text="Days you would realistically take under an unlimited policy, used for scoring",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_planning_days, drop_planning_days),
            ],
        ),
    ]
