from django.db import migrations


class Migration(migrations.Migration):
    # Nile refuses the SET CONSTRAINTS that Django emits around a foreign-key drop:
    # "command tag SET CONSTRAINTS unhandled". Issuing the DDL directly avoids the bookkeeping,
    # the same way 0012 and 0013 work around its refusal of ALTER COLUMN ... DROP DEFAULT.
    atomic = False

    dependencies = [
        ("career", "0033_remove_paycheckactual_actual_federal_tax_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE career_aiartifact DROP COLUMN IF EXISTS source_offer_id;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS career_taxprofile;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.RemoveField(model_name="aiartifact", name="source_offer"),
                migrations.DeleteModel(name="TaxProfile"),
            ],
        ),
    ]
