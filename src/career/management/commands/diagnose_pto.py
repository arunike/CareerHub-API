from django.core.management.base import BaseCommand

from availability.models import CustomHoliday
from career.models import Experience


class Command(BaseCommand):
    help = "Read-only: how each role resolves its PTO allowance, and what the calendar already holds."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--year", type=int, required=True)

    def handle(self, *args, **options):
        year = options["year"]
        roles = Experience.objects.filter(user__email=options["email"]).select_related("offer")
        self.stdout.write(f"{roles.count()} role(s)")
        for role in roles.order_by("-is_current", "-start_date"):
            offer = role.offer
            self.stdout.write(
                f"\nexperience-{role.id} type={role.employment_type!r} current={role.is_current}"
                f"\n  start={role.start_date} end={role.end_date}"
                f"\n  offer={'offer-%s' % offer.id if offer else 'NONE'}"
                f" pto_days={offer.pto_days if offer else '-'}"
                f" unlimited={offer.is_unlimited_pto if offer else '-'}"
                f" planning={offer.unlimited_pto_planning_days if offer else '-'}"
                f" rollover_max={offer.pto_rollover_max_days if offer else '-'}"
            )

        untabbed = CustomHoliday.objects.filter(
            user__email=options["email"], date__year=year
        ).filter(tab__isnull=True) | CustomHoliday.objects.filter(
            user__email=options["email"], date__year=year, tab=""
        )
        self.stdout.write(f"\n--- 'My Time Off' entries in {year} (no holiday tab) ---")
        self.stdout.write(f"  {untabbed.distinct().count()} day(s)")
        for holiday in untabbed.distinct().order_by("date")[:15]:
            self.stdout.write(f"    {holiday.date} {holiday.description or ''!r} type={holiday.holiday_type} locked={holiday.is_locked} group={holiday.group_id}")
