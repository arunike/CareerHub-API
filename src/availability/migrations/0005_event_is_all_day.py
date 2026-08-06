from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("availability", "0004_usersettings_offer_adjustment_settings"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="event",
                    name="is_all_day",
                    field=models.BooleanField(default=False),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "availability_event" '
                    'ADD COLUMN "is_all_day" boolean NOT NULL DEFAULT false;',
                    reverse_sql='ALTER TABLE "availability_event" DROP COLUMN "is_all_day";',
                ),
            ],
        ),
    ]
