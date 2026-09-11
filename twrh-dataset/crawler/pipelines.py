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
from crawler import signals as twrh_signals
from crawler import raw_sink
from crawler import artifact_sink


class CrawlerPipeline(object):

    def __init__(self) -> None:
        super().__init__()
        self.vendorMap = {}
        for vendor in Vendor.objects.all():
            self.vendorMap[vendor.name] = vendor
        if not raw_sink.enabled():
            # D5 後 DB 不存 raw：sink 關＝raw 無處可去；不擋爬，但大聲講
            logging.error(
                'raw has no sink: TWRH_RAW_SINK=0 — raw HTML of this run will be lost')
        # 4a／4b 檔案分區（雙寫期：DB 仍是真相）：list stub 與 parsed 列各自
        # 一個 shard writer；指紋在 RawHouseItem(list) 算好、等同戶的
        # GenericHouseItem 到再寫 stub（兩個 item 同一 response 連續到達）
        self.stub_writer = artifact_sink.ShardWriter('list')
        self.parsed_writer = artifact_sink.ShardWriter('parsed')
        # 4d：deal591 的成交事件（vendor 給的 deal_time／n_day_deal）→ deals 分區
        self.deals_writer = artifact_sink.ShardWriter('deals')
        self._pending_stub = {}      # house_id -> fingerprint
        self._pending_parsed = set()  # house_id（detail dict 已到）
        self._parser_version = None
        try:
            from importlib.metadata import version
            self._parser_version = version('scrapy-tw-rental-house')
        except Exception:  # pragma: no cover
            pass

    def close_spider(self, spider=None):
        self.stub_writer.close()
        self.parsed_writer.close()
        self.deals_writer.close()

    def item_vendor (self, item):
        return self.vendorMap[item['vendor']]

    def write_artifact_rows(self, item, y, m, d):
        '''4a list stub／4b parsed／4d deal event 列 → scratch shard。失敗只記 log、不影響
        DB 寫入（雙寫期 DB 是真相；分區檔缺漏由 artifactpack／manifest 對數抓）。'''
        if not artifact_sink.enabled():
            return
        house_id = item['vendor_house_id']
        date_str = '{:04d}-{:02d}-{:02d}'.format(y, m, d)
        short = artifact_sink.vendor_dirname(item['vendor'])
        run = artifact_sink.run_id()
        now = timezone.now()
        try:
            if artifact_sink.is_deal_event(item):
                self.deals_writer.append(artifact_sink.deal_event_row(
                    short, house_id, date_str, run, now,
                    item['deal_time'], item.get('n_day_deal')))
                return
            if house_id in self._pending_stub:
                fingerprint = self._pending_stub.pop(house_id)
                self.stub_writer.append(artifact_sink.list_stub(
                    short, house_id, date_str, run, now, fingerprint, item))
            if house_id in self._pending_parsed:
                self._pending_parsed.discard(house_id)
                self.parsed_writer.append(artifact_sink.parsed_row(
                    short, house_id, date_str, run, now,
                    self._parser_version, item))
        except Exception:
            logging.exception('artifact row write failed for %s', house_id)

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
                    # 3-1／D5：raw 只進 scratch，收尾 rawpack 打日包上 S3
                    if raw_sink.enabled():
                        raw_sink.write_raw(
                            item['vendor'],
                            '{:04d}-{:02d}-{:02d}'.format(y, m, d),
                            item['house_id'],
                            'list' if item['is_list'] else 'detail',
                            item['raw'])

                if 'dict' in item and not item['is_list']:
                    house_etc.detail_dict = item['dict']
                    self._pending_parsed.add(item['house_id'])

                # list 層指紋（title/price/update_time…）落地供 L-C 比對；
                # 空 dict 不覆寫，避免解析失敗清掉上次的指紋
                fingerprint_changed = False
                if item['is_list'] and item.get('dict'):
                    old_dict = house_etc.list_dict or {}
                    # 指紋只比 price/title：update_time 是「N小時內更新」
                    # 相對字串，隨時間自然流動，直接 diff 會天天誤報
                    fingerprint_changed = bool(old_dict) and any(
                        old_dict.get(key) != item['dict'].get(key)
                        for key in ('price', 'title'))
                    house_etc.list_dict = item['dict']
                    self._pending_stub[item['house_id']] = \
                        artifact_sink.list_fingerprint(item['dict'])

                house_etc.save()

                # 出現在 list 就蓋時間戳——L-B 完整度哨兵（statscheck 算
                # open 中多少在今日 list）與 L-C「在今日 list」謂詞的落地。
                # crawled_at 蓋不了這用途：list/detail 都會動它，分不出來源
                if item['is_list']:
                    now = timezone.now()
                    house.list_crawled_at = now
                    update_fields = ['list_crawled_at', 'updated']
                    if fingerprint_changed:
                        house.list_fingerprint_changed_at = now
                        update_fields.append('list_fingerprint_changed_at')
                    house.save(update_fields=update_fields)
                    house_ts, _ = HouseTS.objects.get_or_create(
                        year=y, month=m, day=d, hour=h,
                        vendor_house_id=item['house_id'],
                        vendor=self.item_vendor(item)
                    )
                    house_ts.list_crawled_at = now
                    house_ts.save(update_fields=['list_crawled_at', 'updated'])
                else:
                    # detail 成功解析才蓋——L-C「距上次 detail < N 天」謂詞用
                    house.detail_crawled_at = timezone.now()
                    house.save(update_fields=['detail_crawled_at', 'updated'])

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

                self.write_artifact_rows(item, y, m, d)

        except Exception as err:
            logging.error('Pipeline got exception in item {}'.format(item))
            traceback.print_exc()
            # 讓熔斷 extension 看得到 storage 層的失敗（dx 2-1）
            crawler = getattr(spider, 'crawler', None)
            if crawler is not None:
                crawler.signals.send_catch_log(
                    twrh_signals.parse_error, spider=spider, exception=err)

        return item
