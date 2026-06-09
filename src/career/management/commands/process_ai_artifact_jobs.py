import time

from django.core.management.base import BaseCommand

from career.services.ai_artifact_jobs import process_next_ai_artifact_generation_job


class Command(BaseCommand):
    help = 'Process queued AI artifact generation jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process one queued job and exit.')
        parser.add_argument('--sleep', type=float, default=2.0, help='Seconds to wait between polls.')

    def handle(self, *args, **options):
        once = options['once']
        sleep_seconds = options['sleep']

        while True:
            job = process_next_ai_artifact_generation_job()
            if job:
                self.stdout.write(f'Processed AI artifact job {job.id}: {job.status}')
            elif once:
                self.stdout.write('No queued AI artifact jobs.')

            if once:
                return
            time.sleep(sleep_seconds)
