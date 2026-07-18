from django.db import migrations, models


COLUMN_DEFINITIONS = {
    'display_title': {
        'postgresql': "varchar(120) DEFAULT '' NOT NULL",
        'sqlite': "varchar(120) DEFAULT '' NOT NULL",
    },
    'event_date_is_user_override': {
        'postgresql': 'boolean DEFAULT false NOT NULL',
        'sqlite': 'bool DEFAULT 0 NOT NULL',
    },
    'notes_is_user_override': {
        'postgresql': 'boolean DEFAULT false NOT NULL',
        'sqlite': 'bool DEFAULT 0 NOT NULL',
    },
    'deleted_by_user_at': {
        'postgresql': 'timestamp with time zone NULL',
        'sqlite': 'datetime NULL',
    },
    'hidden_by_sync_at': {
        'postgresql': 'timestamp with time zone NULL',
        'sqlite': 'datetime NULL',
    },
}


def add_editable_timeline_columns_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor not in {'postgresql', 'sqlite'}:
        return

    TimelineEntry = apps.get_model('career', 'ApplicationTimelineEntry')
    table_name = TimelineEntry._meta.db_table
    with connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

    quote_name = connection.ops.quote_name
    quoted_table = quote_name(table_name)
    with connection.cursor() as cursor:
        for column_name, definitions in COLUMN_DEFINITIONS.items():
            if column_name in existing_columns:
                continue
            cursor.execute(
                f'ALTER TABLE {quoted_table} ADD COLUMN {quote_name(column_name)} '
                f'{definitions[connection.vendor]}'
            )


def protect_existing_timeline_content(apps, schema_editor):
    TimelineEntry = apps.get_model('career', 'ApplicationTimelineEntry')
    quote_name = schema_editor.connection.ops.quote_name
    quoted_table = quote_name(TimelineEntry._meta.db_table)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE {quoted_table} '
            f'SET {quote_name("event_date_is_user_override")} = %s '
            f'WHERE {quote_name("event_date")} IS NOT NULL',
            [True],
        )
        cursor.execute(
            f'UPDATE {quoted_table} '
            f'SET {quote_name("notes_is_user_override")} = %s '
            f'WHERE {quote_name("notes")} <> %s',
            [True, ''],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('career', '0007_offer_sick_leave_unlimited_policy'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_editable_timeline_columns_if_missing,
                    migrations.RunPython.noop,
                ),
                migrations.RunPython(
                    protect_existing_timeline_content,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='applicationtimelineentry',
                    name='display_title',
                    field=models.CharField(blank=True, max_length=120),
                ),
                migrations.AddField(
                    model_name='applicationtimelineentry',
                    name='event_date_is_user_override',
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name='applicationtimelineentry',
                    name='notes_is_user_override',
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name='applicationtimelineentry',
                    name='deleted_by_user_at',
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name='applicationtimelineentry',
                    name='hidden_by_sync_at',
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
        ),
    ]
