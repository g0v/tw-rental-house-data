from datetime import timedelta
from django.utils import timezone
from django.core.management.base import BaseCommand
from django.db.models import Count, IntegerField
# from raven.contrib.django.raven_compat.models import client
from crawlerrequest.models import RequestTS, Stats
from crawlerrequest.enums import RequestType
from rental import models
from rental.models import House, HouseTS, Vendor
from rental.enums import DealStatusType

class Command(BaseCommand):
    help = 'Generate daily crawler statistics and error, if any'
    requires_migrations_checks = True

    def get_vendor_stats(self, vendor_id):
        if vendor_id not in self.stats:
            vendor_stats, created = Stats.objects.get_or_create(
                **self.this_ts,
                vendor=self.vendors[vendor_id]
            )

            # reset everything, so we get latest status
            for field in Stats._meta.get_fields():
                if field.__class__ is IntegerField and field.name.startswith('n_'):
                    setattr(vendor_stats, field.name, 0)

            self.stats[vendor_id] = vendor_stats

        return self.stats[vendor_id]

    def handle(self, *args, **options):
        self.this_ts = {
            'year': models.current_year(),
            'month': models.current_month(),
            'day': models.current_day(),
            'hour': models.current_stepped_hour()
        }

        self.vendors = {}
        for vendor in Vendor.objects.all():
            self.vendors[vendor.id] = vendor

        self.stats = {}

        # get every remaining request, include pending request
        failed_query = RequestTS.objects.filter(
            **self.this_ts
        ).values(
            'request_type',
            'vendor'
        ).annotate(
            count=Count('id')
        )

        for row in failed_query:
            vendor_stats = self.get_vendor_stats(row['vendor'])

            if row['request_type'] == RequestType.LIST:
                vendor_stats.n_list_fail = row['count']
            else:
                vendor_stats.n_fail = row['count']
        
        # get today's successed query
        successed_query = HouseTS.objects.filter(
            **self.this_ts
        ).values(
            'vendor',
            'deal_status'
        ).annotate(
            count=Count('id')
        )

        for row in successed_query:
            vendor_stats = self.get_vendor_stats(row['vendor'])

            if row['deal_status'] == DealStatusType.OPENED:
                # n_crawled = opened + not found + dealt
                vendor_stats.n_crawled = row['count']
            elif row['deal_status'] == DealStatusType.NOT_FOUND:
                vendor_stats.n_closed = row['count']
            elif row['deal_status'] == DealStatusType.DEAL:
                vendor_stats.n_dealt = row['count']

        # get today's new item
        today_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        new_item_query = House.objects.filter(
            created__gte=today_start,
            created__lt=today_end
        ).values(
            'vendor'
        ).annotate(
            count=Count('id')
        )

        for row in new_item_query:
            vendor_stats = self.get_vendor_stats(row['vendor'])
            vendor_stats.n_new_item = row['count']
        
        for vendor_id in self.stats:
            vendor_stats = self.stats[vendor_id]
            vendor_stats.n_crawled += vendor_stats.n_closed + vendor_stats.n_dealt
            vendor_stats.n_expected = vendor_stats.n_crawled + vendor_stats.n_fail
            vendor_stats.save()

            if vendor_stats.n_fail or vendor_stats.n_list_fail:
                errmsg = '{}/{}/{}: Vendor {} get failed list/detail ({}/{}) requests'.format(
                    self.this_ts['year'],
                    self.this_ts['month'],
                    self.this_ts['day'],
                    vendor_stats.vendor.name,
                    vendor_stats.n_list_fail,
                    vendor_stats.n_fail
                )
                print(errmsg)
                # client.captureMessage(errmsg)
            else:
                print('{}/{}/{}: Vendor {} get total/closed/dealt ({}/{}/{}) requests'.format(
                    self.this_ts['year'],
                    self.this_ts['month'],
                    self.this_ts['day'],
                    vendor_stats.vendor.name,
                    vendor_stats.n_crawled,
                    vendor_stats.n_closed,
                    vendor_stats.n_dealt
                ))
