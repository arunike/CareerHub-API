from django.db import migrations

DROP_OLD = """
ALTER TABLE availability_usersettings DROP COLUMN IF EXISTS ignored_federal_holidays;
ALTER TABLE availability_usersettings DROP COLUMN IF EXISTS federal_holiday_color;
"""

RESTORE_OLD = """
ALTER TABLE availability_usersettings
    ADD COLUMN IF NOT EXISTS ignored_federal_holidays jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE availability_usersettings
    ADD COLUMN IF NOT EXISTS federal_holiday_color varchar(32) NOT NULL DEFAULT 'gray';
UPDATE availability_usersettings
    SET ignored_federal_holidays = ignored_observed_holidays,
        federal_holiday_color = observed_holiday_color;
"""


class Migration(migrations.Migration):
    """Separate from 0004 so the drop runs in its own transaction, after 0004's backfill."""

    dependencies = [
        ('availability', '0004_observed_holidays'),
    ]

    operations = [
        migrations.RunSQL(DROP_OLD, RESTORE_OLD),
    ]
