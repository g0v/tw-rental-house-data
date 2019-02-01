import argparse
import shutil
from os import path, mkdir, remove, listdir
from zipfile import ZipFile, ZIP_DEFLATED
from tempfile import mkdtemp
from datetime import datetime, date, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rental.libs.export import UniqExport, RawExport

# TODO: uniq support postgres only

class Command(BaseCommand):
    help = 'Export house data by given time range'
    default_export_dir = 'tw-rental-data'
    zip_dir = path.join(path.dirname(path.realpath(__file__)), '../../../../datas')
    requires_migrations_checks = True

    def parse_date(self, input):
        try: 
            return timezone.make_aware(datetime.strptime(input, '%Y%m%d'))
        except ValueError:
            raise argparse.ArgumentTypeError('Invalid date string: {}'.format(input))

    def add_arguments(self, parser):
        parser.add_argument(
            '-p',
            '--periodic-export',
            dest='is_periodic',
            default=False,
            const=True,
            nargs='?',
            help='perform periodic export'
        )

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

    def handle_manual(self, **options):
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

    def is_end_of_sth(self):
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)

        is_end_of_month = today.month != tomorrow.month
        is_end_of_quarter = False
        is_end_of_year = False

        if is_end_of_month:
            is_end_of_quarter = today.month % 3 == 0
            is_end_of_year = today.month == 12

        return {
            'month': is_end_of_month,
            'quarter': is_end_of_quarter,
            'year': is_end_of_year
        }

    def zip_everything(self, tmp_dir, prefix, type='raw'):
        zip_name = path.join(self.zip_dir, '[{}][CSV][{}] TW-Rental-Data.zip'.format(prefix, type.capitalize()))
        csv_postfix = list(map(lambda name: '-{}{}'.format(type, name), ['-01.csv', '-01.json', '.csv', '.json']))
        with ZipFile(zip_name, 'w', compression=ZIP_DEFLATED) as zip:
            for postfix in csv_postfix:
                filename = '{}{}'.format(prefix, postfix)
                filepath = path.join(tmp_dir, filename)
                if path.isfile(filepath):
                    zip.write(filepath, arcname=path.join(self.default_export_dir, filename))

        for postfix in csv_postfix:
            filename = '{}{}'.format(prefix, postfix)
            filepath = path.join(tmp_dir, filename)
            if path.isfile(filepath):
                remove(filepath)

        zip_name = path.join(self.zip_dir, '[{}][JSON][{}] TW-Rental-Data.zip'.format(prefix, type.capitalize()))
        with ZipFile(zip_name, 'w', compression=ZIP_DEFLATED) as zip:
            for f in listdir(tmp_dir):
                zip.write(path.join(tmp_dir, f), arcname=path.join(self.default_export_dir, f))

    def export_everything(self, from_date, to_date, prefix):

        to_date += timedelta(days=1)
        tmp_dir = mkdtemp()
        outfile_prefix = path.join(tmp_dir, prefix)

        print('#### Export everything in {} ####'.format(prefix))
        uniq = UniqExport()
        raw = RawExport()

        # export tf raw + json
        raw.print(
            from_date,
            to_date,
            print_enum=False,
            outfile='{}-raw'.format(outfile_prefix),
            export_json=True
        )

        self.zip_everything(tmp_dir, prefix, 'raw')
        shutil.rmtree(tmp_dir)

        # export tf uniq + json
        tmp_dir = mkdtemp()
        outfile_prefix = path.join(tmp_dir, prefix)

        uniq.print(
            from_date,
            to_date,
            print_enum=False,
            outfile='{}-deduplicated'.format(outfile_prefix),
            export_json=True
        )

        self.zip_everything(tmp_dir, prefix, 'deduplicated')
        shutil.rmtree(tmp_dir)

    def handle_periodic(self):
        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)

        end_of_sth = self.is_end_of_sth()

        if not end_of_sth['month']:
            return

        # monthly export
        month_ago = today.replace(day=1)
        month_prefix = month_ago.strftime('%Y%m')
        self.export_everything(month_ago, today, month_prefix)

        # quarterly export
        if end_of_sth['quarter']:
            # we are at the end of quarter, no month underflow :)
            quarter_ago = today.replace(month=today.month-2, day=1)
            quarter_prefix = '{}Q{}'.format(today.year, int(today.month/3))
            self.export_everything(quarter_ago, today, quarter_prefix)

        # annual export
        if end_of_sth['year']:
            year_ago = today.replace(month=1, day=1)
            year_prefix = '{}'.format(today.year)
            self.export_everything(year_ago, today, year_prefix)

    def handle(self, *args, **options):
        is_periodic = options['is_periodic'] is not False

        if is_periodic:
            self.handle_periodic()
        else:
            self.handle_manual(**options)
