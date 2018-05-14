import sys
import os
import traceback
from datetime import datetime
sys.path.append('{}/../..'.format(
    os.path.dirname(os.path.realpath(__file__))))


from backend.db.models import House, HouseEtc, db
from backend.crawler.spiders.detail591_spider import Detail591Spider

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
                print('[{}] Done {} rows'.format(datetime.now(), total))
                rows = []
            except:
                traceback.print_exc()
                transaction.rollback()


def parse(page=1):
    global total
    etcs = HouseEtc.select(
        HouseEtc.house,
        HouseEtc.vendor_house_id,
        HouseEtc.detail_dict
    ).where(
        HouseEtc.detail_dict != None
    ).order_by(
        HouseEtc.house
    ).paginate(
        page, 1000
    )

    detailSpider = Detail591Spider()

    count = etcs.count()

    if count == 0:
        return False

    total += count

    for etc in etcs:
        house = etc.house
        try:
            share_attrs = detailSpider.gen_shared_attrs(
                etc.detail_dict, house
            )
            for attr in share_attrs:
                setattr(house, attr, share_attrs[attr])
                setattr(house, attr, share_attrs[attr])
            save(house)
        except:
            print('error in {} in page {}'.format(house.id, page))
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
