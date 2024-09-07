# -*- coding: utf-8 -*-

# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://doc.scrapy.org/en/latest/topics/item-pipeline.html

import logging
import traceback
from django.utils import timezone
from rental.models import HouseTS, House, HouseEtc, Vendor, Author
from rental.enums import DealStatusType
from scrapy_twrh.items import GenericHouseItem, RawHouseItem
from django.contrib.gis.geos import Point
from crawler.utils import now_tuple


class CrawlerPipeline(object):

    def __init__(self) -> None:
        super().__init__()
        self.vendorMap = {}
        for vendor in Vendor.objects.all():
            self.vendorMap[vendor.name] = vendor

    def item_vendor (self, item):
        return self.vendorMap[item['vendor']]

    def process_item(self, item, spider):
        y, m, d, h = now_tuple()

        try:
            if type(item) is RawHouseItem:

                house, created = House.objects.get_or_create(
                    vendor_house_id=item['house_id'],
                    vendor=self.item_vendor(item)
                )

                house_etc, created = HouseEtc.objects.get_or_create(
                    house=house,
                    vendor_house_id=item['house_id'],
                    vendor=self.item_vendor(item)
                )

                if 'raw' in item:
                    if item['is_list']:
                        house_etc.list_raw = item['raw']
                    else:
                        house_etc.detail_raw = item['raw']

                if 'dict' in item and not item['is_list']:
                    house_etc.detail_dict = item['dict']

                house_etc.save()

            elif type(item) is GenericHouseItem:
                house_ts, created = HouseTS.objects.get_or_create(
                    year=y, month=m, day=d, hour=h,
                    vendor_house_id=item['vendor_house_id'],
                    vendor=self.item_vendor(item)
                )

                house, created = House.objects.get_or_create(
                    vendor_house_id=item['vendor_house_id'],
                    vendor=self.item_vendor(item)
                )

                to_db = item.copy()
                del to_db['vendor']
                del to_db['vendor_house_id']

                # Issue #9
                # if the house has been dealt, keep its deal_status
                should_rollback_house_deal_status = False
                if 'deal_status' in to_db and \
                    to_db['deal_status'] == DealStatusType.NOT_FOUND and \
                    house.deal_status == DealStatusType.DEAL:
                    should_rollback_house_deal_status = True

                if 'rough_coordinate' in to_db:
                    to_db['rough_coordinate'] = Point(to_db['rough_coordinate'], srid=4326)
                if 'author' in to_db:
                    author_info, created = Author.objects.get_or_create(truth=to_db['author'])
                    to_db['author'] = author_info

                for attr in to_db:
                    setattr(house_ts, attr, to_db[attr])
                    setattr(house, attr, to_db[attr])

                house.crawled_at = timezone.now()
                house_ts.crawled_at = timezone.now()

                if should_rollback_house_deal_status:
                    # don't update crawled_at either
                    house.deal_status = DealStatusType.DEAL

                house.save()
                house_ts.save()

        except:
            logging.error('Pipeline got exception in item {}'.format(item))
            traceback.print_exc()

        return item
