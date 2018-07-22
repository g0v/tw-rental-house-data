import sys
import os
import traceback
import json
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

rows = []
total = 0
current_count = 0
transaction_size = 500


def save(row, force=False):
    global rows
    global total
    global current_count
    global transaction_size
    if row:
        rows.append(row)
    if len(rows) >= transaction_size or force:
        with transaction.atomic():
            try:
                for r in rows:
                    r.save()
                print('[{}] Done {}/{} rows'.format(timezone.localtime(), current_count, total))
                rows = []
            except:
                traceback.print_exc()


def parse():
    global total
    global current_count
    global transaction_size
    etcs = HouseEtc.objects.filter(
        detail_dict__isnull=False
    ).order_by(
        'house'
    ).values(
        'house',
        'vendor_house_id',
        'detail_dict'
    )

    paginator = Paginator(etcs, transaction_size)
    detailSpider = Detail591Spider()

    total = paginator.count
    print('==== Total {} rows to rerun ===='.format(total))

    for page_num in paginator.page_range:
        etcs_page = paginator.page(page_num)

        for etc in etcs_page:
            house = House.objects.get(pk=etc['house'])
            try:
                detail_dict = json.loads(etc['detail_dict'])
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


if __name__ == '__main__':
    parse()
