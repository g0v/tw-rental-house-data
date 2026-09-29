# -*- coding: utf-8 -*-

# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://doc.scrapy.org/en/latest/topics/item-pipeline.html

import logging
import os
import traceback
from rental import tz as timezone   # S6：無 Django（同介面）
from scrapy_twrh.items import GenericHouseItem, RawHouseItem
from crawler.utils import now_tuple
from crawler import signals as twrh_signals
from crawler import raw_sink
from crawler import artifact_sink


class CrawlerPipeline(object):

    '''S6：唯一落地是檔案——raw 進 scratch（rawpack 打日包）、normalized 列進 scratch shard
    （artifactpack 打 list／parsed／deals 分區）。House／HouseTS／HouseEtc 寫入隨 DB 退場移除。'''

    def __init__(self) -> None:
        super().__init__()
        if not raw_sink.enabled():
            # D5 後 DB 不存 raw：sink 關＝raw 無處可去；不擋爬，但大聲講
            logging.error(
                'raw has no sink: TWRH_RAW_SINK=0 — raw HTML of this run will be lost')
        if not artifact_sink.enabled():
            logging.error(
                'items have no sink: TWRH_ARTIFACT_SINK=0 — '
                'everything parsed in this run will be lost')
        # 4a／4b 檔案分區：list stub 與 parsed 列各自
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

    def write_artifact_rows(self, item, y, m, d):
        '''4a list stub／4b parsed／4d deal event 列 → scratch shard。寫失敗＝掉資料：往上丟，
        process_item 的 except 送 parse_error 給熔斷 extension。'''
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
            raise

    def process_item_files_only(self, item, y, m, d):
        '''全部工作——raw 進 scratch、list 指紋與 detail dict
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
            self.process_item_files_only(item, y, m, d)
        except Exception as err:
            logging.error('Pipeline got exception in item {}'.format(item))
            traceback.print_exc()
            # 讓熔斷 extension 看得到 storage 層的失敗（dx 2-1）
            crawler = getattr(spider, 'crawler', None)
            if crawler is not None:
                crawler.signals.send_catch_log(
                    twrh_signals.parse_error, spider=spider, exception=err)

        return item
