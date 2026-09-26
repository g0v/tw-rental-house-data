# -*- coding: utf-8 -*-

# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://doc.scrapy.org/en/latest/topics/item-pipeline.html

import logging
import os
import traceback
from rental import tz as timezone   # S6：無 Django（同介面）
# DB 分支（TWRH_HOUSE_DB=1 回退）才用得到的 model：延遲載入，檔案時代不起 Django
from crawler.orm import HouseTS, House, HouseEtc, Author, Point
from rental.switches import house_db
from rental import vendors
from rental.enums import DealStatusType
from scrapy_twrh.items import GenericHouseItem, RawHouseItem
from crawler.utils import now_tuple
from crawler import signals as twrh_signals
from crawler import raw_sink
from crawler import artifact_sink


def etc_db_write():
    '''house_etc 還要不要寫（S2：預設不寫）。

    整份 detail_dict 自 S2a 起落在 parsed 分區的 `vendor_extra`、snapshot 也攜帶最新
    一次，所以 DB 這份是重複的；`list_dict` 只服務已退役的 DB 種子判準（S1 起判準
    改讀 snapshot 的 carry 欄）。歷史那份由 S2b 的 RDS export 永久保存。
    回退＝環境 `TWRH_ETC_DB_WRITE=1`（house_etc 若已 drop 就回退不了，見 migration）。
    '''
    return os.environ.get('TWRH_ETC_DB_WRITE', '0') == '1'


class CrawlerPipeline(object):

    def __init__(self) -> None:
        super().__init__()
        self.vendorMap = {}
        for vendor in vendors.all():
            self.vendorMap[vendor.name] = vendor
        if not raw_sink.enabled():
            # D5 後 DB 不存 raw：sink 關＝raw 無處可去；不擋爬，但大聲講
            logging.error(
                'raw has no sink: TWRH_RAW_SINK=0 — raw HTML of this run will be lost')
        if not house_db() and not artifact_sink.enabled():
            logging.error(
                'items have no sink: house DB is off (S3b) and TWRH_ARTIFACT_SINK=0 — '
                'everything parsed in this run will be lost')
        # 4a／4b 檔案分區（S3b 起是唯一落地；TWRH_HOUSE_DB=1 回退時才又是雙寫）：list stub 與 parsed 列各自
        # 一個 shard writer；指紋在 RawHouseItem(list) 算好、等同戶的
        # GenericHouseItem 到再寫 stub（兩個 item 同一 response 連續到達）
        self.stub_writer = artifact_sink.ShardWriter('list')
        self.parsed_writer = artifact_sink.ShardWriter('parsed')
        # 4d：deal591 的成交事件（vendor 給的 deal_time／n_day_deal）→ deals 分區
        self.deals_writer = artifact_sink.ShardWriter('deals')
        self._pending_stub = {}      # house_id -> fingerprint
        self._pending_parsed = {}     # house_id -> detail dict（已到，等同戶的 GenericHouseItem）
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
            if artifact_sink.is_closure(item):
                # detail 404／拒解析：沒有 detail dict 也要留一列（只帶 deal_status），
                # snapshot fold 才看得到關閉；欄位全 NULL 與 DB 的 NOT_FOUND 列同形
                self.parsed_writer.append(artifact_sink.parsed_row(
                    short, house_id, date_str, run, now, self._parser_version, item))
                return
            if house_id in self._pending_stub:
                fingerprint = self._pending_stub.pop(house_id)
                self.stub_writer.append(artifact_sink.list_stub(
                    short, house_id, date_str, run, now, fingerprint, item))
            if house_id in self._pending_parsed:
                detail_dict = self._pending_parsed.pop(house_id)
                self.parsed_writer.append(artifact_sink.parsed_row(
                    short, house_id, date_str, run, now,
                    self._parser_version, item, vendor_extra=detail_dict))
        except Exception:
            logging.exception('artifact row write failed for %s', house_id)
            if not house_db():
                # S3b：分區檔是唯一落地，寫失敗＝掉資料，不能只記 log——往上丟，
                # process_item 的 except 會送 parse_error 給熔斷 extension
                raise

    def process_item_files_only(self, item, y, m, d):
        '''S3b：house／house_ts 停寫後的全部工作——raw 進 scratch、list 指紋與 detail dict
        暫存到同戶的 GenericHouseItem 到、normalized 列落 scratch shard。
        （DEAL sticky、list_crawled_at、detail_crawled_at、Author 這些 DB 端語意都已由
        snapshot fold 的 carry 欄接手；parsed 列的 author 只留雜湊、不需要 Author 表。）'''
        if type(item) is RawHouseItem:
            if 'raw' in item and raw_sink.enabled():
                raw_sink.write_raw(
                    item['vendor'], '{:04d}-{:02d}-{:02d}'.format(y, m, d),
                    item['house_id'], 'list' if item['is_list'] else 'detail', item['raw'])
            if 'dict' in item and not item['is_list']:
                self._pending_parsed[item['house_id']] = item['dict']
            if item['is_list'] and item.get('dict'):
                self._pending_stub[item['house_id']] = \
                    artifact_sink.list_fingerprint(item['dict'])
        elif type(item) is GenericHouseItem:
            self.write_artifact_rows(item, y, m, d)

    def process_item(self, item, spider):
        y, m, d, h = now_tuple()

        try:
            if not house_db():
                self.process_item_files_only(item, y, m, d)
                return item

            if type(item) is RawHouseItem:

                house, created = House.objects.get_or_create(
                    vendor_house_id=item['house_id'],
                    vendor=self.item_vendor(item)
                )

                # S2：停寫之後連 get_or_create 都不做（table 會被 drop）
                house_etc = None
                if etc_db_write():
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
                    # S2：house_etc 退役，整份 dict 只進 parsed 列的 vendor_extra
                    # （回退＝TWRH_ETC_DB_WRITE=1，見 etc_db_write）
                    if house_etc is not None:
                        house_etc.detail_dict = item['dict']
                    self._pending_parsed[item['house_id']] = item['dict']

                # list 層指紋（title/price/update_time…）落地供 L-C 比對；
                # 空 dict 不覆寫，避免解析失敗清掉上次的指紋
                fingerprint_changed = False
                if item['is_list'] and item.get('dict'):
                    # S2：list_dict 停寫。指紋比對（供 House.list_fingerprint_changed_at）
                    # 本來拿舊 list_dict 比新的，停寫後沒有比對基礎——那個欄位只服務
                    # 已退役的 DB 種子判準（S1 起判準改讀 snapshot 的
                    # fingerprint_at_last_detail 對今日 stub 指紋），所以一起停止維護。
                    # DB 判準當回退時 fingerprint 類會少排，stale／absent／returned 仍在。
                    if house_etc is not None:
                        old_dict = house_etc.list_dict or {}
                        # 指紋只比 price/title：update_time 是「N小時內更新」
                        # 相對字串，隨時間自然流動，直接 diff 會天天誤報
                        fingerprint_changed = bool(old_dict) and any(
                            old_dict.get(key) != item['dict'].get(key)
                            for key in ('price', 'title'))
                        house_etc.list_dict = item['dict']
                    self._pending_stub[item['house_id']] = \
                        artifact_sink.list_fingerprint(item['dict'])

                if house_etc is not None:
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
