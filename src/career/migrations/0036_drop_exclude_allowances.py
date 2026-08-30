from django.db import migrations


class Migration(migrations.Migration):
    # A separate migration so the DROP does not follow 0035's UPDATE inside one transaction,
    # which Postgres refuses for pending trigger events.
    dependencies = [
        ("career", "0035_deferral_base"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE career_incomeyear "
                    "DROP COLUMN IF EXISTS exclude_allowances_from_deferral_base;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="incomeyear",
                    name="exclude_allowances_from_deferral_base",
                ),
            ],
        ),
    ]
