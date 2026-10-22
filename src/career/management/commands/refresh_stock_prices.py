from django.core.management.base import BaseCommand

from career.tasks import refresh_tracked_stock_prices


class Command(BaseCommand):
    help = "Refresh the latest price for every ticker any account tracks."

    def handle(self, *args, **options):
        self.stdout.write(refresh_tracked_stock_prices())
