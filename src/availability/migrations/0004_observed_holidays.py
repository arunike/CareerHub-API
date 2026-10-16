from django.db import migrations, models

# Nile rejects RENAME COLUMN, so the rename is an add and a backfill; 0005 drops the old pair.
ADD_AND_COPY = """
ALTER TABLE availability_usersettings
    ADD COLUMN IF NOT EXISTS ignored_observed_holidays jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE availability_usersettings
    ADD COLUMN IF NOT EXISTS observed_holiday_color varchar(32) NOT NULL DEFAULT 'gray';
UPDATE availability_usersettings
    SET ignored_observed_holidays = ignored_federal_holidays,
        observed_holiday_color = federal_holiday_color;
UPDATE availability_customholiday SET holiday_type = 'observed' WHERE holiday_type = 'federal';
"""

# Every ALTER precedes every UPDATE: an ALTER after one is refused for pending trigger events.
DROP_NEW = """
ALTER TABLE availability_usersettings DROP COLUMN IF EXISTS ignored_observed_holidays;
ALTER TABLE availability_usersettings DROP COLUMN IF EXISTS observed_holiday_color;
UPDATE availability_customholiday SET holiday_type = 'federal' WHERE holiday_type = 'observed';
"""


class Migration(migrations.Migration):

    dependencies = [
        ('availability', '0003_customholiday_pto_experience_ids'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(ADD_AND_COPY, DROP_NEW)],
            state_operations=[
                migrations.RenameField(
                    model_name='usersettings',
                    old_name='ignored_federal_holidays',
                    new_name='ignored_observed_holidays',
                ),
                migrations.RenameField(
                    model_name='usersettings',
                    old_name='federal_holiday_color',
                    new_name='observed_holiday_color',
                ),
                migrations.AlterField(
                    model_name='usersettings',
                    name='ignored_observed_holidays',
                    field=models.JSONField(
                        default=list, help_text='Observed holiday names or dates to ignore'
                    ),
                ),
                migrations.AlterField(
                    model_name='usersettings',
                    name='observed_holiday_color',
                    field=models.CharField(
                        default='gray',
                        help_text='Colour for the observed holidays tab',
                        max_length=32,
                    ),
                ),
            ],
        ),
    ]
