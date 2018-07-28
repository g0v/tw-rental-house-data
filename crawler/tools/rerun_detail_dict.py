import sys
import os
import traceback
import json
import argparse
from django.utils import timezone
from django.db import transaction
from django.core.paginator import Paginator
from scrapy.http import Request, HtmlResponse

sys.path.append('{}/..'.format(
    os.path.dirname(os.path.realpath(__file__))))

from tools.utils import load_django
load_django()

from rental.models import House, HouseEtc
from crawler.spiders.detail591_spider import Detail591Spider

# Allow rerun in parallel, as id is sequential
PARTITION_SIZE = 30000
TRANSACTION_SIZE = 500

rows = []
total = 0
current_count = 0



def save(row, force=False):
    global rows
    global total
    global current_count
    global TRANSACTION_SIZE
    if row:
        rows.append(row)
    if len(rows) >= TRANSACTION_SIZE or force:
        with transaction.atomic():
            try:
                for r in rows:
                    r.save()
                print('[{}] Done {}/{} rows'.format(timezone.localtime(), current_count, total))
                rows = []
            except:
                traceback.print_exc()


def parse(partition_size, partition_index):
    global total
    global current_count
    global TRANSACTION_SIZE

    id_lower = partition_size * partition_index
    id_upper = partition_size * (partition_index + 1)

    etcs = HouseEtc.objects.filter(
        detail_dict__isnull=False,
        house_id__gte=id_lower,
        house_id__lt=id_upper
    ).order_by(
        'house'
    ).values(
        'house',
        'vendor_house_id',
        'detail_dict'
    )

    paginator = Paginator(etcs, TRANSACTION_SIZE)
    detailSpider = Detail591Spider()

    total = paginator.count
    print('==== Total {} rows in id[{}:{}] to rerun ===='.format(total, id_lower, id_upper))

    for page_num in paginator.page_range:
        etcs_page = paginator.page(page_num)

        for etc in etcs_page:
            house = House.objects.get(pk=etc['house'])
            try:
                if type(etc['detail_dict']) is dict:
                    detail_dict = etc['detail_dict']
                else:
                    detail_dict = etc['detail_dict']

                share_attrs = detailSpider.gen_shared_attrs(
                    detail_dict, house
                )
                for attr in share_attrs:
                    setattr(house, attr, share_attrs[attr])
                    setattr(house, attr, share_attrs[attr])
                current_count += 1
                save(house)
            except:
                print('error in {}'.format(house.id))
                traceback.print_exc()

    save(None, True)


def parse_number(input):
    try:
        return int(input, 10)
    except ValueError:
        raise argparse.ArgumentTypeError('Invalid number: {}'.format(input))

arg_parser = argparse.ArgumentParser(description='Rerun parser from raw html to update house table')
arg_parser.add_argument(
    '-ps',
    '--partition-size',
    dest='partition_size',
    default=PARTITION_SIZE,
    type=parse_number,
    help='size of one partition, default {}'.format(PARTITION_SIZE)
)

arg_parser.add_argument(
    '-pi',
    '--partition-index',
    dest='partition_index',
    default=0,
    type=parse_number,
    help='which partition to run'
)

if __name__ == '__main__':
    args = arg_parser.parse_args()
    
    partition_size = args.partition_size
    partition_index = args.partition_index

    parse(partition_size, partition_index)
