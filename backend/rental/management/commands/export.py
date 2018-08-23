import argparse
from datetime import datetime, date, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rental.libs.export import UniqExport, RawExport

# TODO: uniq support postgres only

class Command(BaseCommand):
    help = 'Export house data by given time range'
    requires_migrations_checks = True

    def parse_date(self, input):
        try: 
            return timezone.make_aware(datetime.strptime(input, '%Y%m%d'))
        except ValueError:
            raise argparse.ArgumentTypeError('Invalid date string: {}'.format(input))

    def add_arguments(self, parser):
        parser.add_argument(
            '-u',
            '--unique',
            default=False,
            const=True,
            nargs='?',
            help='remove duplicated item or not'
        )

        parser.add_argument(
            '-e',
            '--enum',
            default=False,
            const=True,
            nargs='?',
            help='print enumeration or not'
        )

        parser.add_argument(
            '-f',
            '--from',
            dest='from_date',
            default=None,
            type=self.parse_date,
            help='from date, format: YYYYMMDD, default today'
        )

        parser.add_argument(
            '-t',
            '--to',
            dest='to_date',
            default=None,
            type=self.parse_date,
            help='to date, format: YYYYMMDD, default today'
        )

        parser.add_argument(
            '-o',
            '--outfile',
            default='rental_house',
            help='output file name, without postfix(.csv)'
        )

        parser.add_argument(
            '-j',
            '--json',
            default=False,
            const=True,
            nargs='?',
            help='export json or not, each top region will be put in seperated files'
        )

        parser.add_argument(
            '-b6',
            '--big6',
            default=False,
            const=True,
            nargs='?',
            help='only export 六都'
        )

        parser.add_argument(
            '-01',
            '--01-instead-of-truefalse',
            dest='use_01',
            default=False,
            const=True,
            nargs='?',
            help='use T/F to express boolean value in csv, instead of 1/0'
        )

    def handle(self, *args, **options):
        need_uniq = options['unique'] is not False
        print_enum = options['enum'] is not False
        want_json = options['json'] is not False
        use_tf = options['use_01'] is not True
        big6 = options['big6'] is not False
        from_date = options['from_date']
        to_date = options['to_date']

        if from_date is None:
            from_date = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if to_date is None:
            to_date = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if from_date > to_date:
            from_date, to_date = to_date, from_date

        to_date += timedelta(days=1)

        if need_uniq:
            tool = UniqExport()
        else:
            tool = RawExport()

        tool.print(
            from_date,
            to_date,
            print_enum=print_enum,
            only_big6=big6,
            outfile=options['outfile'],
            export_json=want_json,
            use_tf=use_tf
        )
