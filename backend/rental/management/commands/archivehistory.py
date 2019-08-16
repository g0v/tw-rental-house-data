from os import path, makedirs
from datetime import timedelta, datetime
from uuid import UUID
import json
from django.core.management.base import BaseCommand, CommandError
from django.forms.models import model_to_dict
from django.utils import timezone
from django.core.paginator import Paginator
from django.contrib.gis.geos import Point

from rental.models import HouseEtc, HouseTS

# Src: https://stackoverflow.com/questions/36588126/uuid-is-not-json-serializable
class GeneralEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            # if the obj is uuid, we simply return the value of uuid
            return obj.hex
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Point):
            return obj.coords
        return json.JSONEncoder.default(self, obj)

def parse_date(input):
    try:
        the_date = timezone.make_aware(datetime.strptime(input, '%Y-%m-%d'))
    except ValueError:
        raise CommandError('Expect date strig format: %Y-%m-%d')
    return the_date

def parse_positive_integer(input):
    try:
        value = int(input, 10)
    except ValueError:
        raise CommandError('Expect --days-ago to be an integer, but get {}'.format(input))

    if value <= 0:
        raise CommandError('Expect --days-ago to be >= 0')

    return value


class Command(BaseCommand):
    help = 'Archive unused time series and raw data.'
    requires_migrations_checks = True
    default_days_ago = 60
    items_per_page = 3000

    def add_arguments(self, parser):
        parser.add_argument('output_dir')

        parser.add_argument(
            '-b',
            '--before-date',
            dest='before_date',
            type=parse_date,
            default=None,
            help='Archieve all time series before given date, in ISO-8601 format'
        )

        parser.add_argument(
            '-d',
            '--days-ago',
            dest='days_ago',
            type=parse_positive_integer,
            default=None,
            help='Archieve all time series older than given number of day. Default 60 days if neither -b nor -d are given.'
        )

    def handle(self, *args, **options):
        output = options['output_dir']

        if not path.isdir(output):
            raise CommandError('Directory {} not existed'.format(output))

        if options['before_date'] and options['days_ago']:
            raise CommandError('Donot use --before-date and --days-ago at the same time -___-')

        before_date = timezone.localdate()

        if options['before_date']:
            before_date = options['before_date']
        elif options['days_ago']:
            before_date -= timedelta(options['days_ago'])
        else:
            before_date -= timedelta(self.default_days_ago)

        self.remove_old_ts(output, before_date)

    def remove_old_ts(self, output_dir, before_date: datetime.date):
        before_date += timedelta(1)
        old_houses = HouseTS.objects.filter(
            created__lt=before_date
        )

        total_house = old_houses.count()
        pages = Paginator(old_houses, self.items_per_page)
        n_done = 0
        self.stdout.ending = ''
        self.stdout.write("[HouseTS] Start to backup {} rows before {}.\n".format(
            total_house,
            before_date.isoformat()
        ))

        for page_num in pages.page_range:
            for house in pages.page(page_num):
                sub_dir = 'ts/{:04d}/{:02d}/{:02d}'.format(house.created.year, house.created.month, house.created.day)
                filename = 'house.{}.{}.json'.format(house.vendor.name, house.vendor_house_id)
                self.dump_row(
                    base_dir=output_dir,
                    sub_dir=sub_dir,
                    filename=filename,
                    house=house
                )
                house.delete()
                n_done += 1
                self.stdout.write("\r[HouseTS] {:3.0f}% done".format(
                    100 * n_done / total_house
                ))
        
        self.stdout.write("\n[HouseTS] done!\n")
        self.stdout.ending = '\n'

    def dump_row(self, base_dir, sub_dir, filename, house):
        target_dir = path.join(base_dir, sub_dir)
        makedirs(target_dir, exist_ok=True)

        plain_obj = model_to_dict(house)
        with open(path.join(target_dir, filename), 'w') as dest_file:
            json.dump(plain_obj, dest_file, ensure_ascii=False, cls=GeneralEncoder)
