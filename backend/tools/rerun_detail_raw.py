import sys
import os
import traceback
import traceback
sys.path.append('{}/../..'.format(
    os.path.dirname(os.path.realpath(__file__))))


from backend.db.models import House, HouseEtc, db
from backend.crawler.spiders.detail591_spider import Detail591Spider
from scrapy.http import Request, HtmlResponse
from backend.crawler.items import RawHouseItem, GenericHouseItem

rows = []
total = 0


def save(row, force=False):
    global rows
    global total
    if row:
        rows.append(row)
    if len(rows) >= 1000 or force:
        with db.atomic() as transaction:
            try:
                for r in rows:
                    r.save()
                print('Done {} rows'.format(total))
                rows = []
            except:
                traceback.print_exc()
                transaction.rollback()


def parse(page=1):
    global total
    etcs = HouseEtc.select(
        HouseEtc.house,
        HouseEtc.vendor_house_id,
        HouseEtc.detail_raw
    ).where(
        HouseEtc.detail_raw != None
    ).order_by(
        HouseEtc.house
    ).paginate(
        page, 1000
    )

    detailSpider = Detail591Spider()

    count = etcs.count()

    if count == 0:
        return False

    total += count*2

    for etc in etcs:
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
            print('error in {} in page {}'.format(request.meta['seed'], page))
            traceback.print_exc()

    return True


if __name__ == '__main__':
    page = 1
    while True:
        ret = parse(page)
        page += 1
        if not ret:
            break
    save(None, True)
