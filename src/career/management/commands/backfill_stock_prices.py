from django.core.management.base import BaseCommand

from career.services.stock_quotes import SERIES_PERIODS
from career.tasks import backfill_tracked_stock_prices


class Command(BaseCommand):
    help = "Fill the daily price log from the provider for every ticker any account tracks."

    def add_arguments(self, parser):
        parser.add_argument('--period', default='2y', choices=SERIES_PERIODS)

    def handle(self, *args, **options):
        self.stdout.write(backfill_tracked_stock_prices(options['period']))
