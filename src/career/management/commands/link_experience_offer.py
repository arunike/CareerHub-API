from django.core.management.base import BaseCommand, CommandError

from career.models import Experience, Offer


class Command(BaseCommand):
    help = "Point an experience at an offer, so they stop appearing as two income roles."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--experience", type=int, required=True)
        parser.add_argument("--offer", type=int, required=True)
        parser.add_argument("--apply", action="store_true", help="Without this the command only reports.")

    def handle(self, *args, **options):
        role = Experience.objects.filter(
            user__email=options["email"], id=options["experience"]
        ).first()
        if not role:
            raise CommandError("No such experience for that account")
        offer = Offer.objects.filter(id=options["offer"]).select_related("application").first()
        if not offer:
            raise CommandError("No such offer")

        app = offer.application
        offer_company = app.company.name if app and app.company else ""
        self.stdout.write(f"experience-{role.id} {role.company!r} / {role.title!r}")
        self.stdout.write(f"  currently linked to: {role.offer_id or 'NONE'}")
        self.stdout.write(f"offer-{offer.id} {offer_company!r} base={offer.base_salary}")

        if role.company.strip().lower() != offer_company.strip().lower():
            raise CommandError(
                f"Refusing: company mismatch ({role.company!r} vs {offer_company!r})"
            )
        claimed = Experience.objects.filter(offer_id=offer.id).exclude(id=role.id).first()
        if claimed:
            raise CommandError(f"Refusing: offer already claimed by experience-{claimed.id}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("\nDry run. Re-run with --apply to link them."))
            return

        role.offer_id = offer.id
        role.save(update_fields=["offer"])
        role.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(f"\nLinked: experience-{role.id}.offer = {role.offer_id}"))
