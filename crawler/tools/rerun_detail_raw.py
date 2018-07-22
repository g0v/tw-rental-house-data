import sys
import os
import traceback
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from scrapy.http import Request, HtmlResponse

sys.path.append('{}/..'.format(
    os.path.dirname(os.path.realpath(__file__))))

from tools.utils import load_django
load_django()

from crawler.spiders.detail591_spider import Detail591Spider
from crawler.items import RawHouseItem, GenericHouseItem
from rental.models import House, HouseEtc


rows = []
total = 0
cur_count = 0


def save(row, force=False):
    global rows
    global total
    global cur_count
    if row:
        rows.append(row)
    if len(rows) >= 1000 or force:
        with transaction.atomic():
            try:
                for r in rows:
                    r.save()
                print('[{}] Done {}/{} rows'.format(timezone.localtime(), cur_count, total))
                rows = []
            except:
                traceback.print_exc()


def parse():
    global total
    global cur_count
    etcs = HouseEtc.objects.filter(
        detail_raw__isnull=False
    ).order_by(
        'house'
    )

    paginator = Paginator(etcs, 1000)
    detailSpider = Detail591Spider()

    total = paginator.count
    print('==== Total {} rows to rerun ===='.format(total))

    for page_num in paginator.page_range:
        etcs_page = paginator.page(page_num)
        for etc in etcs_page:
            cur_count += 1
            request = Request(**detailSpider.gen_request_params({
                'house_id': etc.vendor_house_id
            }))
            response = HtmlResponse(
                '',
                status=200,
                request=request,
                body=etc.detail_raw.encode('utf-8')
            )
            try:
                for item in detailSpider.parse_detail(response):
                    if type(item) is RawHouseItem:
                        if 'dict' in item and not item['is_list']:
                            etc.detail_dict = item['dict']
                            save(etc)
                    elif type(item) is GenericHouseItem:
                        to_db = item.copy()
                        house = etc.house
                        del to_db['vendor']
                        del to_db['vendor_house_id']

                        for attr in to_db:
                            if attr in to_db:
                                setattr(house, attr, to_db[attr])

                        save(house)
            except:
                print('error in {}'.format(request.meta['seed']))
                traceback.print_exc()

    save(None, True)


if __name__ == '__main__':
    parse()
    
