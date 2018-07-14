from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import connections
from rental.models import SubRegion, House, HouseEtc, RegionTS, HouseTS
from crawler.models import RequestTS

import json

class Command(BaseCommand):
    help = 'All migration tasks from peewee to Django that cannot be perfromed using built-in facilities'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            '--db',
            dest='db_name',
            help='Specify db to migrate'
        )

    def handle(self, *args, **options):
        db_name = 'default'

        if options['db_name']:
            db_name = options['db_name']

        if db_name not in settings.DATABASES:
            raise CommandError('DB {} is not defined in settings'.format(db_name))

        if 'postgresql' not in settings.DATABASES[db_name]['ENGINE']:
            raise CommandError('Only PostgreSQL is required for manual migration :)')

        target_models = [House, HouseEtc, RegionTS, HouseTS, RequestTS]

        for model in target_models:
            db_table = model._meta.db_table
            sql = 'select column_name, data_type from INFORMATION_SCHEMA.COLUMNS where ' \
                "table_name = %s and data_type = 'timestamp without time zone'"
            
            tz_fields = []
            with connections[db_name].cursor() as cursor:
                cursor.execute(sql, [db_table])
                
                for row in cursor.fetchall():
                    tz_fields.append(row[0])

                if len(tz_fields) > 0:
                    self.stdout.write('{} | migrating timestamp to timestamptz'.format(db_table))
            
                for field in tz_fields:
                    self.stdout.write('{}::{} | alter type to timestamptz'.format(db_table, field))
                    cursor.execute('alter table {} alter {} type timestamptz'.format(db_table, field))
        
        self.stdout.write('Migration done~~')
