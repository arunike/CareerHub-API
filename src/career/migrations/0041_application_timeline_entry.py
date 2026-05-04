from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("career", "0040_application_decision_scorecard_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApplicationTimelineEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("APPLIED", "Applied"),
                            ("OA", "Online Assessment"),
                            ("SCREEN", "Phone Screen"),
                            ("ONSITE", "Onsite Interview"),
                            ("OFFER", "Offer"),
                            ("REJECTED", "Rejected"),
                            ("ACCEPTED", "Accepted"),
                            ("GHOSTED", "Ghosted"),
                        ],
                        max_length=20,
                    ),
                ),
                ("stage_order", models.PositiveSmallIntegerField(default=999)),
                ("event_date", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="timeline_entries",
                        to="career.application",
                    ),
                ),
                (
                    "documents",
                    models.ManyToManyField(blank=True, related_name="timeline_entries", to="career.document"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="application_timeline_entries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["application_id", "stage_order"],
            },
        ),
        migrations.AddConstraint(
            model_name="applicationtimelineentry",
            constraint=models.UniqueConstraint(
                fields=("user", "application", "stage"),
                name="unique_timeline_stage_per_application",
            ),
        ),
    ]
