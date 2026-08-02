from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0017_offer_equity_refresh_and_offer_letter_type"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "career_applicationtimelineentry" '
                'DROP COLUMN IF EXISTS "reminder_date";'
            ),
            # Recreated nullable; the original data is gone either way.
            reverse_sql=(
                'ALTER TABLE "career_applicationtimelineentry" '
                'ADD COLUMN IF NOT EXISTS "reminder_date" date NULL;'
            ),
        ),
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "career_applicationtimelineentry" '
                'DROP COLUMN IF EXISTS "reminder_note";'
            ),
            reverse_sql=(
                'ALTER TABLE "career_applicationtimelineentry" '
                "ADD COLUMN IF NOT EXISTS \"reminder_note\" text NOT NULL DEFAULT '';"
            ),
        ),
    ]
