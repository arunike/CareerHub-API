from django.db import migrations, models


def blank_unknown_decision_signals(apps, schema_editor):
    Application = apps.get_model("career", "Application")
    Application.objects.filter(visa_sponsorship="UNKNOWN").update(visa_sponsorship="")
    Application.objects.filter(day_one_gc="UNKNOWN").update(day_one_gc="")


def restore_unknown_decision_signals(apps, schema_editor):
    Application = apps.get_model("career", "Application")
    Application.objects.filter(visa_sponsorship="").update(visa_sponsorship="UNKNOWN")
    Application.objects.filter(day_one_gc="").update(day_one_gc="UNKNOWN")


class Migration(migrations.Migration):
    dependencies = [
        ("career", "0041_application_timeline_entry"),
    ]

    operations = [
        migrations.RunPython(blank_unknown_decision_signals, restore_unknown_decision_signals),
        migrations.AlterField(
            model_name="application",
            name="day_one_gc",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Not specified"),
                    ("YES", "Yes"),
                    ("NO", "No"),
                    ("NOT_APPLICABLE", "Not applicable"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="visa_sponsorship",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Not specified"),
                    ("NOT_NEEDED", "Not needed"),
                    ("AVAILABLE", "Sponsorship available"),
                    ("TRANSFER_ONLY", "Transfer only"),
                    ("NOT_AVAILABLE", "No sponsorship"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
