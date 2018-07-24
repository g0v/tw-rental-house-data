# -*- coding: utf-8 -*-

# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://doc.scrapy.org/en/latest/topics/item-pipeline.html

import logging
import traceback
from rental.models import HouseTS, House, HouseEtc
from .items import GenericHouseItem, RawHouseItem
from crawler.utils import now_tuple


class CrawlerPipeline(object):

    def process_item(self, item, spider):
        y, m, d, h = now_tuple()

        try:
            if type(item) is RawHouseItem:

                house, created = House.objects.get_or_create(
                    vendor_house_id=item['house_id'],
                    vendor=item['vendor']
                )

                house_etc, created = HouseEtc.objects.get_or_create(
                    house=house,
                    vendor_house_id=item['house_id'],
                    vendor=item['vendor']
                )

                if 'raw' in item:
                    if item['is_list']:
                        house_etc.list_raw = item['raw']
                    else:
                        house_etc.detail_raw = item['raw'].decode(
                            'utf-8', 'backslashreplace')

                if 'dict' in item and not item['is_list']:
                    house_etc.detail_dict = item['dict']

                house_etc.save()

            elif type(item) is GenericHouseItem:
                house_ts, created = HouseTS.objects.get_or_create(
                    year=y, month=m, day=d, hour=h,
                    vendor_house_id=item['vendor_house_id'],
                    vendor=item['vendor']
                )

                house, created = House.objects.get_or_create(
                    vendor_house_id=item['vendor_house_id'],
                    vendor=item['vendor']
                )

                to_db = item.copy()
                del to_db['vendor']
                del to_db['vendor_house_id']

                for attr in to_db:
                    if attr in to_db:
                        setattr(house_ts, attr, to_db[attr])
                        setattr(house, attr, to_db[attr])


                house.save()
                house_ts.save()

        except:
            logging.error('Pipeline got exception in item {}'.format(item))
            traceback.print_exc()

        return item
