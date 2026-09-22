from django.core.management.base import BaseCommand

from career.models import Experience, IncomeYear, Offer


class Command(BaseCommand):
    help = "Read-only: show how each role resolves its pay and whether raises can reach it."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    def handle(self, *args, **options):
        roles = (
            Experience.objects.filter(user__email=options["email"])
            .select_related("offer")
            .order_by("-is_current", "-start_date")
        )
        self.stdout.write(f"{roles.count()} role(s)")
        for role in roles:
            offer = role.offer
            raises = (offer.raise_history if offer else None) or []
            self.stdout.write(
                f"\nexperience-{role.id} | current={role.is_current}"
                f"\n  base_salary={role.base_salary} hourly_rate={role.hourly_rate}"
                f"\n  offer={'offer-%s' % offer.id if offer else 'NONE'}"
                f" offer_base={offer.base_salary if offer else '-'}"
                f"\n  raises_on_offer={len(raises)}"
            )
            for entry in raises:
                self.stdout.write(
                    f"    date={entry.get('date')} effective={entry.get('effective_date')}"
                    f" base_before={entry.get('base_before')} base_after={entry.get('base_after')}"
                )

        self.stdout.write("\n--- saved Income years ---")
        for year in IncomeYear.objects.filter(user__email=options["email"]).order_by("-tax_year"):
            self.stdout.write(
                f"{year.tax_year} {year.source_key or '(no source)'}"
                f" salary_override={year.salary_override}"
                f" paychecks_override={year.paychecks_per_year_override}"
                f" first_pay_date={year.first_pay_date}"
                f" salary_ovr={year.salary_override} bonus_ovr={year.bonus_override}"
                f" grant_ovr={year.total_grant_override}"
            )

        self.stdout.write("\n--- source_key referential check ---")
        exp_ids = set(Experience.objects.filter(user__email=options["email"]).values_list("id", flat=True))
        offer_ids = set(
            Offer.objects.filter(application__user__email=options["email"]).values_list("id", flat=True)
        ) | set(
            Experience.objects.filter(user__email=options["email"], offer__isnull=False).values_list(
                "offer_id", flat=True
            )
        )
        for year in IncomeYear.objects.filter(user__email=options["email"]):
            key = year.source_key or ""
            kind, _, raw = key.partition("-")
            alive = (
                (kind == "experience" and raw.isdigit() and int(raw) in exp_ids)
                or (kind == "offer" and raw.isdigit() and int(raw) in offer_ids)
            )
            if not alive:
                self.stdout.write(f"  ORPHAN {year.tax_year} source_key={key!r}")
        self.stdout.write("  (no ORPHAN lines above means every key resolves)")

        self.stdout.write("\n--- current offers and whether an experience claims them ---")
        claimed = dict(
            Experience.objects.filter(user__email=options["email"], offer__isnull=False).values_list(
                "offer_id", "id"
            )
        )
        for offer in Offer.objects.filter(
            application__user__email=options["email"]
        ).select_related("application"):
            app = offer.application
            self.stdout.write(
                f"  offer-{offer.id} application={'yes' if app else 'NONE'}"
                f" company={(app.company.name if app and app.company else '(no application)')!r}"
                f" role={(getattr(app, 'role_title', '') if app else '')!r} base={offer.base_salary}"
                f" claimed_by={'experience-%s' % claimed[offer.id] if offer.id in claimed else 'NOBODY'}"
                f"\n     premiums/paycheck: health={offer.health_premium_paycheck} dental={offer.dental_premium_paycheck}"
                f" vision={offer.vision_premium_paycheck}"
                f"\n     dependents: has={offer.has_dependents} health={offer.dependent_health_premium_paycheck}"
                f" dental={offer.dependent_dental_premium_paycheck} vision={offer.dependent_vision_premium_paycheck}"
            )

        self.stdout.write("\n--- stored per-paycheck overrides that pin a gross ---")
        for year in IncomeYear.objects.filter(user__email=options["email"]).order_by("-tax_year"):
            rows = year.period_deductions or []
            pinned = [r for r in rows if isinstance(r, dict) and r.get("regularGross") is not None]
            self.stdout.write(
                f"{year.tax_year} {year.source_key}: {len(rows)} override row(s), {len(pinned)} pinning a gross"
            )
            for row in pinned:
                keys = ", ".join(k for k in row if k != "periodIndex")
                self.stdout.write(f"    periodIndex={row.get('periodIndex')} regularGross={row['regularGross']} keys=[{keys}]")
