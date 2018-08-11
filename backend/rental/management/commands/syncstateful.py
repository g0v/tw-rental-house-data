import argparse
import traceback
from datetime import datetime, date
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction
from rental.models import House, HouseEtc, HouseTS
from rental.enums import DealStatusType

class Command(BaseCommand):
    help = 'Update all stateful column which is not handled by crawler. Default update only item of today.'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            '-ts',
            '--timeseries',
            dest='update_ts',
            default=False,
            const=True,
            nargs='?',
            help='Whether to update timeseries table or not. Only works when not reseting all items.'
        )

        parser.add_argument(
            '-r',
            '--reset',
            dest='need_reset',
            default=False,
            const=True,
            nargs='?',
            help='Whether to update all item or not.'
        )

    def handle(self, *args, **options):
        need_reset = options['need_reset'] is not False
        update_ts = options['update_ts'] is not False
        target_date = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

        self.update_deal_info(need_reset, target_date, update_ts)

    def update_deal_info(self, need_reset, target_date, update_ts):
        n_updated = 0

        if need_reset:
            houses = House.objects.exclude(deal_status=DealStatusType.OPENED)
        else:
            houses = HouseTS.objects.filter(
                year=target_date.year,
                month=target_date.month,
                day=target_date.day,
                hour=target_date.hour,
            ).exclude(
                deal_status=DealStatusType.OPENED
            )

        def do_update(vendor, house_id, deal_info, target_date):
            House.objects.filter(vendor=vendor, vendor_house_id=house_id).update(**deal_info)

        if update_ts and not need_reset:
            def do_update(vendor, house_id, deal_info, target_date):
                House.objects.filter(vendor=vendor, vendor_house_id=house_id).update(**deal_info)
                HouseTS.objects.filter(
                    year=target_date.year,
                    month=target_date.month,
                    day=target_date.day,
                    hour=target_date.hour,
                    vendor=vendor,
                    vendor_house_id=house_id
                ).update(**deal_info)

        total_updated = houses.count()

        with transaction.atomic():
            try:
                for house in houses.values('vendor', 'vendor_house_id'):
                    deal_info = self.get_last_deal_info(house['vendor'], house['vendor_house_id'])
                    if deal_info:
                        do_update(house['vendor'], house['vendor_house_id'], deal_info, target_date)

                    n_updated += 1
                    if n_updated % 500 == 0:
                        print('[{}] Done {}/{} rows'.format(timezone.localtime(), n_updated, total_updated))
            except:
                traceback.print_exc()

        print('[{}] Done {}/{} rows'.format(timezone.localtime(), n_updated, total_updated))


    def get_day_from_ts(self, ts_row):
        return date(ts_row.year, ts_row.month, ts_row.day)

    def get_last_deal_info(self, vendor, vendor_house_id):
        """
        Possible state transition (from before to now to future):
        deal than closed: O O O D D D D N N N          => D by 3
        closed than deal: O O O N N N D D D N N        => D by 6 
        closed than open thean deal: O O O N N O O D D => D by 7 
        repeatedly closed: O O N N O O N N             => N
        repeatedly closed: O O N N O O                 => O
        reopen: O O D . . . O O O D                    => D by 3
        """
        house_historys = HouseTS.objects.filter(
            vendor=vendor, vendor_house_id=vendor_house_id
        ).order_by(
            '-updated'
        )

        last_cont_status = []
        later_date = None

        for history in house_historys:
            if not later_date:
                later_date = self.get_day_from_ts(history)
            else:
                cur_date = self.get_day_from_ts(history)
                delta_day = later_date - cur_date
                if delta_day.days != 1:
                    break
                later_date = cur_date
            
            last_cont_status.append({
                'date': later_date,
                'deal_status': history.deal_status,
                'row': history
            })

        prev_status = None
        deal_tail = None
        deal_head = len(last_cont_status)-1
        # deal time should happen between [D,!D] - [!D,D]
        for (i, status) in enumerate(last_cont_status):
            if not prev_status:
                prev_status = status
                continue
            if deal_tail is not None:
                if status['deal_status'] == DealStatusType.DEAL:
                    deal_head = i-1
                    break
            elif prev_status['deal_status'] == DealStatusType.DEAL and\
                prev_status['deal_status'] != status['deal_status']:
                deal_tail = i-1

            prev_status = status

        if len(last_cont_status) == 0:
            return None

        if deal_head == 0 and prev_status['deal_status'] == DealStatusType.DEAL:
            deal_tail = 0

        if deal_tail is None:
            # can't find any deal data
            ret = {
                'deal_status': last_cont_status[0]['deal_status'],
                'deal_time': None,
                'n_day_deal': None
            }
        else:
            ret = {
                'deal_status': DealStatusType.DEAL,
                'deal_time': last_cont_status[deal_tail]['row'].created,
                'n_day_deal': deal_head - deal_tail + 1
            }

        # print(vendor_house_id, '{}-{}'.format(deal_tail, deal_head), ret)
        return ret
