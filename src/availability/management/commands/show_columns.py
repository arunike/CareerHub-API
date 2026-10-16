from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = 'Print a table\'s columns and nullability. Reads schema only, never row data.'

    def add_arguments(self, parser):
        parser.add_argument('table')
        parser.add_argument('--like', default='', help='Only columns containing this text')

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT column_name, data_type, is_nullable, column_default'
                ' FROM information_schema.columns'
                ' WHERE table_name = %s ORDER BY ordinal_position',
                [options['table']],
            )
            rows = cursor.fetchall()
        if not rows:
            raise CommandError(f"no table named {options['table']}")
        for name, data_type, nullable, default in rows:
            if options['like'] and options['like'] not in name:
                continue
            null = 'NULL' if nullable == 'YES' else 'NOT NULL'
            self.stdout.write(f'{name}\t{data_type}\t{null}\tdefault={default}')
