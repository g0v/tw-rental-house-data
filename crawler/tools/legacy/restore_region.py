import sys
import os
import traceback
import json
sys.path.append('{}/../..'.format(
    os.path.dirname(os.path.realpath(__file__))))

from backend.db.models import House, HouseEtc, db
from backend.db.enums import TopRegionField, SubRegionField


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
                print('Done {}/{} rows'.format(len(rows), total))
                total -= len(rows)
                rows = []
            except:
                traceback.print_exc()
                transaction.rollback()


def restore():
    global total
    houses = House.select(
        House.id,
        House.top_region,
        House.sub_region
    )
    total = houses.count()
    for house in houses:
        try:
            etc = HouseEtc.get(
                HouseEtc.house == house
            )
            dd = etc.detail_dict
            lr = etc.list_raw
            if lr:
                try:
                    lr = json.loads(lr)
                except json.decoder.JSONDecodeError:
                    lr = eval(lr)
                    etc.list_raw = json.dumps(lr, ensure_ascii=False)
                    total += 1
                    save(etc)

            if dd and 'top_region' in dd and dd['top_region']:
                sub_region = '{}{}'.format(dd['top_region'], dd['sub_region'])
                house.top_region = getattr(
                    TopRegionField.enums, dd['top_region'])
                house.sub_region = getattr(
                    SubRegionField.enums, sub_region)
                save(house)
            elif lr and 'region_name' in lr and lr['region_name']:
                sub_region = '{}{}'.format(lr['region_name'], lr['section_name'])
                house.top_region = getattr(
                    TopRegionField.enums, lr['region_name'])
                house.sub_region = getattr(
                    SubRegionField.enums, sub_region)
                save(house)
            else:
                print('Cannot help for house {}'.format(house.id))
        except HouseEtc.DoesNotExist:
            print('Cannot found house {}'.format(house.id))


if __name__ == '__main__':
    restore()
    save(None, True)
