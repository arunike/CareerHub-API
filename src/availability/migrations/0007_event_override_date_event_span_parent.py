import django.db.models.deletion
from django.db import migrations, models

FK_NAME = "availability_event_span_parent_id_fk"
INDEX_NAME = "availability_event_span_parent_id_idx"


def add_span_parent(_apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        # SQLite accepts the inline REFERENCES form, which is what Django emits there.
        schema_editor.execute(
            'ALTER TABLE "availability_event" ADD COLUMN "span_parent_id" bigint NULL '
            'REFERENCES "availability_event" ("id") DEFERRABLE INITIALLY DEFERRED;'
        )
        schema_editor.execute(
            f'CREATE INDEX "{INDEX_NAME}" ON "availability_event" ("span_parent_id");'
        )
        return

    schema_editor.execute(
        'ALTER TABLE "availability_event" ADD COLUMN "span_parent_id" bigint NULL;'
    )
    schema_editor.execute(
        f'ALTER TABLE "availability_event" ADD CONSTRAINT "{FK_NAME}" '
        'FOREIGN KEY ("span_parent_id") REFERENCES "availability_event" ("id") '
        "ON DELETE CASCADE;"
    )
    schema_editor.execute(
        f'CREATE INDEX "{INDEX_NAME}" ON "availability_event" ("span_parent_id");'
    )


def drop_span_parent(_apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        schema_editor.execute(f'DROP INDEX IF EXISTS "{INDEX_NAME}";')
        schema_editor.execute(
            'ALTER TABLE "availability_event" DROP COLUMN "span_parent_id";'
        )
        return
    schema_editor.execute(f'DROP INDEX IF EXISTS "{INDEX_NAME}";')
    schema_editor.execute(
        f'ALTER TABLE "availability_event" DROP CONSTRAINT IF EXISTS "{FK_NAME}";'
    )
    schema_editor.execute('ALTER TABLE "availability_event" DROP COLUMN "span_parent_id";')


class Migration(migrations.Migration):
    dependencies = [
        ("availability", "0006_event_end_date"),
    ]

    operations = [
        # Plain nullable column, no default: the generated SQL is already safe here.
        migrations.AddField(
            model_name="event",
            name="override_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="event",
                    name="span_parent",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="day_overrides",
                        to="availability.event",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_span_parent, drop_span_parent),
            ],
        ),
    ]
