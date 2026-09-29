'''CrawlerPipeline（只落檔）、item 衛生、list591 前緣掃描、deal591 deals stage。'''
import json
import os
import unittest
from unittest import mock

import scrapy
from scrapy.http import TextResponse

from tests.helpers import (TEST_DATE, VENDOR_NAME, TempEnvTestCase, pack, track, write_latest,
                           write_shard)


def seeds(type_name):
    from rental import filequeue
    return list(filequeue.load_seeds('591', TEST_DATE, type_name)[0].values())


class PipelineTests(TempEnvTestCase):
    '''唯一落地是檔案：raw → raws/scratch、normalized 列 → artifacts/scratch shard。'''

    def pipeline(self):
        from crawler.pipelines import CrawlerPipeline
        return CrawlerPipeline()

    def test_pipeline_writes_stub_and_parsed_rows(self):
        from rental import artifacts, contracts, enums
        from scrapy_twrh.items import GenericHouseItem, RawHouseItem
        pipeline = self.pipeline()
        list_dict = {'price': '1萬', 'title': 'x'}
        pipeline.process_item(RawHouseItem(house_id='h1', vendor=VENDOR_NAME, is_list=True,
                                           dict=list_dict), None)
        pipeline.process_item(GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='h1',
                                               monthly_price=10000), None)
        pipeline.process_item(RawHouseItem(house_id='h1', vendor=VENDOR_NAME, is_list=False,
                                           dict={'side_metas': {'型態': '公寓'}}), None)
        pipeline.process_item(GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='h1',
                                               monthly_price=10000, floor_ping=12.5,
                                               deal_status=enums.DealStatusType.OPENED), None)
        pipeline.close_spider()
        pack(self, 'list')
        pack(self, 'parsed')
        stubs = list(artifacts.read_list_stubs('591', TEST_DATE))
        parsed = artifacts.read_parsed_rows('591', TEST_DATE)
        self.assertEqual([(s['vendor_house_id'], s['monthly_price'], s['fingerprint'], s['run'])
                          for s in stubs], [('h1', 10000, contracts.list_fingerprint(list_dict), 'run')])
        self.assertEqual([(r['vendor_house_id'], r['floor_ping'], r['deal_status']) for r in parsed],
                         [('h1', 12.5, 0)])
        # 整份 detail_dict 落 vendor_extra（parsed_version 2；house_etc 停寫後它的家）
        self.assertEqual(json.loads(parsed[0]['vendor_extra']), {'side_metas': {'型態': '公寓'}})

    def test_not_found_item_writes_closure_parsed_row(self):
        from rental import artifacts, enums
        from scrapy_twrh.items import GenericHouseItem
        pipeline = self.pipeline()
        pipeline.process_item(GenericHouseItem(
            vendor=VENDOR_NAME, vendor_house_id='gone', deal_status=enums.DealStatusType.NOT_FOUND), None)
        pipeline.close_spider()
        pack(self, 'parsed')
        rows = artifacts.read_parsed_rows('591', TEST_DATE)
        self.assertEqual([(r['vendor_house_id'], r['deal_status'], r['monthly_price'], r['vendor_extra'])
                          for r in rows], [('gone', int(enums.DealStatusType.NOT_FOUND), None, None)])

    def test_deal_event_item_goes_to_deals_partition(self):
        from datetime import datetime
        from rental import artifacts, enums, tz
        from scrapy_twrh.items import GenericHouseItem
        deal_time = tz.make_aware(datetime(2026, 1, 14))
        pipeline = self.pipeline()
        pipeline.process_item(GenericHouseItem(
            vendor=VENDOR_NAME, vendor_house_id='sold', vendor_house_url='https://rent.591.com.tw/sold',
            deal_status=enums.DealStatusType.DEAL, deal_time=deal_time, n_day_deal=5), None)
        pipeline.close_spider()
        pack(self, 'deals')
        self.assertEqual([(r['vendor_house_id'], r['deal_time'], r['n_day_deal'])
                          for r in artifacts.read_deal_events('591', TEST_DATE)], [('sold', deal_time, 5)])
        self.assertEqual(artifacts.read_parsed_rows('591', TEST_DATE), [])

    def test_raw_html_goes_to_scratch_when_sink_on(self):
        from rental import raws
        from scrapy_twrh.items import RawHouseItem
        with mock.patch.dict(os.environ, {'TWRH_RAW_SINK': '1'}):
            pipeline = self.pipeline()
            pipeline.process_item(RawHouseItem(house_id='h1', vendor=VENDOR_NAME, is_list=False,
                                               raw='<html>頁</html>', dict={}), None)
            pipeline.close_spider()
        path = os.path.join(raws.day_dir(VENDOR_NAME, TEST_DATE), 'h1.detail.html')
        with open(path, encoding='utf-8') as f:
            self.assertEqual(f.read(), '<html>頁</html>')

    def test_artifact_write_failure_is_not_swallowed(self):
        '''分區檔是唯一落地：寫失敗要讓熔斷 extension 看得到，不能只記 log。'''
        from rental import enums
        from scrapy_twrh.items import GenericHouseItem
        from crawler import signals as twrh_signals
        pipeline = self.pipeline()
        sent = []
        spider = mock.Mock()
        spider.crawler.signals.send_catch_log.side_effect = lambda sig, **k: sent.append((sig, k))
        with mock.patch('crawler.artifact_sink.parsed_row', side_effect=RuntimeError('disk full')):
            item = GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='gone',
                                    deal_status=enums.DealStatusType.NOT_FOUND)
            self.assertIs(pipeline.process_item(item, spider), item)
        pipeline.close_spider()
        self.assertEqual(len(sent), 1)
        self.assertIs(sent[0][0], twrh_signals.parse_error)
        self.assertIsInstance(sent[0][1]['exception'], RuntimeError)


class ItemHygieneTests(TempEnvTestCase):
    '''list 的 tag 版 facilities 不蓋 detail 的完整清單；detail 的 None rough_address 不蓋 list 給的地址。'''

    def test_strip_functions_are_pure_and_key_scoped(self):
        from crawler.spiders.item_hygiene import strip_list_item, strip_detail_item
        from scrapy_twrh.items import GenericHouseItem
        li = GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='a', monthly_price=1,
                              facilities={'電梯': True}, rough_address='中山北路二段')
        self.assertIs(strip_list_item(li), li)
        self.assertNotIn('facilities', li)
        self.assertEqual((li['monthly_price'], li['rough_address']), (1, '中山北路二段'))
        strip_list_item(GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='b'))
        di = GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='a', rough_address=None,
                              facilities={'桌子': True, '冰箱': False})
        self.assertIs(strip_detail_item(di), di)
        self.assertNotIn('rough_address', di)
        self.assertEqual(di['facilities'], {'桌子': True, '冰箱': False})
        di2 = GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='a', rough_address='忠孝東路')
        strip_detail_item(di2)
        self.assertEqual(di2['rough_address'], '忠孝東路')

    def test_pipeline_and_fold_keep_detail_facilities_and_list_address(self):
        from crawler.spiders.item_hygiene import strip_list_item, strip_detail_item
        from rental import artifacts, snapshot
        from scrapy_twrh.items import GenericHouseItem, RawHouseItem
        from crawler.pipelines import CrawlerPipeline
        detail_fac = {'桌子': True, '椅子': True, '冰箱': False}

        def list_round(pipeline, facilities):
            pipeline.process_item(RawHouseItem(house_id='h', vendor=VENDOR_NAME, is_list=True,
                                               dict={'price': '1萬', 'title': 't'}), None)
            pipeline.process_item(strip_list_item(GenericHouseItem(
                vendor=VENDOR_NAME, vendor_house_id='h', monthly_price=10000,
                rough_address='中山北路二段', facilities=facilities)), None)
        pipeline = CrawlerPipeline()
        list_round(pipeline, {'電梯': True})
        pipeline.process_item(RawHouseItem(house_id='h', vendor=VENDOR_NAME, is_list=False, dict={}), None)
        pipeline.process_item(strip_detail_item(GenericHouseItem(
            vendor=VENDOR_NAME, vendor_house_id='h', monthly_price=10000,
            rough_address=None, facilities=dict(detail_fac))), None)
        list_round(pipeline, {'電梯': True, '陽台': True})       # 隔輪 list 又來
        pipeline.close_spider()
        pack(self, 'list')
        pack(self, 'parsed')
        stubs = list(artifacts.read_list_stubs('591', TEST_DATE))
        parsed = artifacts.read_parsed_rows('591', TEST_DATE)
        self.assertTrue(all('facilities' not in s for s in stubs))
        self.assertIsNone(parsed[0]['rough_address'])
        row = snapshot.fold([], stubs, parsed, [], TEST_DATE)[0]
        self.assertEqual((json.loads(row['facilities']), row['rough_address']), (detail_fac, '中山北路二段'))

    def test_spiders_strip_at_yield(self):
        '''接線驗證：list591 的 yield 點與 detail591 的 yield 點都經過 hygiene。'''
        from crawler.spiders.list591_spider import List591Spider
        from crawler.spiders.detail591_spider import Detail591Spider
        from scrapy_twrh.items import GenericHouseItem, RawHouseItem
        raw = RawHouseItem(house_id='h', raw=b'', dict={})
        gen = lambda: GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='h',  # noqa: E731
                                       facilities={'電梯': True}, rough_address=None)
        ls = List591Spider.__new__(List591Spider)
        ls.frontier_pages = 0
        ls.default_parse_list = lambda response: iter([raw, gen()])
        out = list(ls.parse_list_and_stop(None))
        self.assertNotIn('facilities', out[1])
        self.assertIs(out[0], raw)
        self.assertIs(out[-1], True)
        ds = Detail591Spider.__new__(Detail591Spider)
        ds.default_parse_detail = lambda response: iter([gen()])
        out = list(ds.parse_detail_and_done(None))
        self.assertNotIn('rough_address', out[0])
        self.assertEqual(out[0]['facilities'], {'電梯': True})
        self.assertIs(out[-1], True)


class FrontierSweepTests(TempEnvTestCase):
    '''前緣掃描（短命物件）：list 前緣逐頁、整頁已知（總表＋今日 stub＋本行程已見）即收單。'''

    @staticmethod
    def list_body(ids):
        return ''.join(
            '<div class="item"><div class="item-info-title">'
            '<a href="https://rent.591.com.tw/{}">t</a></div></div>'.format(h) for h in ids)

    def spider(self, **kwargs):
        from crawler.spiders.list591_spider import List591Spider
        spider = List591Spider(target_cities='台北市', **kwargs)
        track(spider.persist_queue)
        return spider

    def frontier_parse(self, spider, page, ids):
        from scrapy_twrh.spiders.rental591.util import ListRequestMeta
        request = scrapy.Request(url='https://rent.591.com.tw/list?region=1&page={}'.format(page + 1),
                                 meta={'rental': ListRequestMeta('1', '台北市', page)})
        response = TextResponse(url=request.url, status=200, body=self.list_body(ids).encode('utf-8'),
                                request=request, encoding='utf-8')
        out = list(spider.parse_list_and_stop(response))
        self.assertIs(out[-1], True)
        return [o for o in out if not isinstance(o, bool)]

    def list_pages(self):
        return sorted(s['page'] for s in seeds('list'))

    def test_frontier_reseeds_every_city_on_each_round_but_daily_run_does_not(self):
        from rental import filequeue as fq
        with mock.patch.dict(os.environ, {'TWRH_RUN_ID': 'sweep-0800'}):
            first = self.spider(frontier_pages=5)
            self.assertEqual(len(list(first.start_list_from_persist_queue())), 1)
            term = fq.TerminalWriter('591', TEST_DATE, 'list', 'sweep-0800', 'w')
            term.append('sweep-0800#id=1|name=台北市|page=0', 'done', 1)
            term.close()
        with mock.patch.dict(os.environ, {'TWRH_RUN_ID': 'sweep-1100'}):
            # 當日已有這縣市的種子，前緣掃描仍重生（同日多輪是它的本意）
            self.assertEqual(len(list(self.spider(frontier_pages=5).start_list_from_persist_queue())), 1)
            # 日跑同日重跑：縣市已排過就不重生，沒爬完的由 queue 自己續（這裡全 done／在飛）
            self.assertEqual(self.spider().ran_today({'id': '1'}), True)
        self.assertEqual(len(seeds('list')), 2)

    @unittest.expectedFailure
    def test_append_same_run_recrawls_list(self):
        '''list591 docstring：append 模式「always regenerate seeds」。檔案 queue 的 list key 帶 run，
        同一個 run（flow run --append 仍是 'run'）重生的 (縣市, page 0) 種子與已 done 的同 key、
        被摺掉 → 不爬。同 DealStageTests.test_append_forces_reseed_and_recrawl。'''
        from rental import filequeue as fq
        first = list(self.spider().start_list_from_persist_queue())[0].meta['db_request']
        term = fq.TerminalWriter('591', TEST_DATE, 'list', 'run', 'w')
        term.append(first.key, 'done', 1)
        term.close()
        self.assertEqual(list(self.spider().start_list_from_persist_queue()), [])   # 非 append：續 queue
        self.assertEqual(len(list(self.spider(append=True).start_list_from_persist_queue())), 1)

    def test_frontier_pages_next_page_only_while_unseen(self):
        write_latest({'k1': {'deal_status': 0}, 'k2': {'deal_status': 1}})
        spider = self.spider(frontier_pages=5)
        # 第 1 頁有沒見過的 → 排第 2 頁
        items = self.frontier_parse(spider, 0, ['n1', 'k1', 'n2'])
        self.assertGreaterEqual(len([i for i in items if isinstance(i, scrapy.Item)]), 3)
        self.assertEqual((self.list_pages(), spider.frontier_new), ([1], 2))
        # 第 2 頁：k1／k2 在總表（含已關閉）、n1 是上一頁剛看到的 → 整頁已知，收單
        self.frontier_parse(spider, 1, ['k1', 'k2', 'n1'])
        self.assertEqual((self.list_pages(), spider.frontier_new), ([1], 2))

    def test_frontier_today_stubs_count_as_known(self):
        from tests.helpers import write_stubs
        write_stubs(self, ['s1', 's2'], run='sweep-0500')          # 今天稍早一輪看到的
        spider = self.spider(frontier_pages=5)
        self.frontier_parse(spider, 0, ['s1', 's2'])
        self.assertEqual((self.list_pages(), spider.frontier_new), ([], 0))

    def test_frontier_page_cap_stops_even_with_unseen(self):
        spider = self.spider(frontier_pages=2)
        self.frontier_parse(spider, 1, ['n1', 'n2'])   # 第 2 頁＝上限
        self.assertEqual(seeds('list'), [])

    def test_frontier_empty_page_raises(self):
        spider = self.spider(frontier_pages=5)
        with self.assertRaises(Exception):
            # 空頁沒有 .item／.paging／.empty → package 判版式不明、丟例外
            self.frontier_parse(spider, 0, [])


class DealStageTests(TempEnvTestCase):
    '''deals stage（#229）：DEAL 類 queue 種子／續跑、未知物件過濾、翻頁到 lookback 窗外即停。'''

    DEAL_BODY = (
        '<html><body><script>window.__NUXT__=(function(a,b,c){return {data:{x:{'
        'data:{dealDataList:['
        '{id:c,url:"https:\\u002F\\u002Frent.591.com.tw\\u002Fknown1",deal_total_day:"9天成交",deal_time:"今日"},'
        '{id:"ghost1",url:"https:\\u002F\\u002Frent.591.com.tw\\u002Fghost1",deal_total_day:"3天成交",deal_time:"昨日"},'
        '{id:"known2",url:"https:\\u002F\\u002Frent.591.com.tw\\u002Fknown2",deal_total_day:"5天成交",deal_time:"9天前"}'
        '],total:3}}}}}(0,"","known1"))</script></body></html>'
    )

    def spider(self, **kwargs):
        from crawler.spiders.deal591_spider import Deal591Spider
        kwargs.setdefault('target_cities', '台北市')
        spider = Deal591Spider(**kwargs)
        track(spider.persist_queue)
        return spider

    def deal_response(self):
        from scrapy_twrh.spiders.rental591.util import DealRequestMeta
        request = scrapy.Request(url='https://rent.591.com.tw/list?shType=clinch&region=1&page=1',
                                 meta={'rental': DealRequestMeta('1', '台北市', 1)})
        return TextResponse(url=request.url, status=200, body=self.DEAL_BODY.encode('utf-8'),
                            request=request, encoding='utf-8')

    def test_seeds_page_one_per_city_with_pinned_base_date(self):
        spider = self.spider(lookback_days=3)
        requests = list(spider.start_deal_from_persist_queue())
        self.assertEqual(len(requests), 1)
        self.assertEqual(seeds('deal'), [{'id': '1', 'name': '台北市', 'page': 1}])
        self.assertEqual(spider.deal_lookback_days, 3)
        self.assertEqual(spider.deal_base_date.isoformat(), TEST_DATE)   # 基準日＝queue 日期
        self.assertIn('shType=clinch', requests[0].url)
        self.assertIn('region=1&page=1', requests[0].url)

    def test_same_day_rerun_does_not_reseed(self):
        from rental import filequeue as fq
        first = list(self.spider().start_deal_from_persist_queue())[0].meta['db_request']
        term = fq.TerminalWriter('591', TEST_DATE, 'deal', 'run', 'w')
        term.append(first.key, 'done', 1)
        term.close()
        self.assertEqual(list(self.spider().start_deal_from_persist_queue()), [])
        self.assertEqual(len(seeds('deal')), 1)

    @unittest.expectedFailure
    def test_append_forces_reseed_and_recrawl(self):
        '''deal591 docstring／CLAUDE.md：--append 強制重生種子（同日再走一次成交列表）。
        檔案 queue 的 deal key 不帶 run（make_key 只對 list 帶 run），同一顆 {id, name, page:1}
        種子與已 done 的那顆同 key、被摺掉 → append 靜默什麼都不爬。DB 時代是新列、會重爬。'''
        from rental import filequeue as fq
        first = list(self.spider().start_deal_from_persist_queue())[0].meta['db_request']
        term = fq.TerminalWriter('591', TEST_DATE, 'deal', 'run', 'w')
        term.append(first.key, 'done', 1)
        term.close()
        self.assertEqual(len(list(self.spider(append='True').start_deal_from_persist_queue())), 1)

    def test_parse_writes_known_houses_only_and_stops_past_window(self):
        from rental import enums
        write_latest({'known1': {'deal_status': 0}, 'known2': {'deal_status': 0}})
        spider = self.spider(lookback_days=2)
        spider.persist_queue.gen_persist_request({'id': '1', 'name': '台北市', 'page': 1})

        out = list(spider.parse_deal_and_stop(self.deal_response()))
        events = [o for o in out if not isinstance(o, bool)]
        # known1 今日→事件；ghost1 沒見過→略過（計數）；known2 9 天前→窗外
        self.assertEqual([e['vendor_house_id'] for e in events], ['known1'])
        self.assertEqual(events[0]['deal_status'], enums.DealStatusType.DEAL)
        self.assertEqual(events[0]['deal_time'].date().isoformat(), TEST_DATE)
        self.assertEqual(events[0]['n_day_deal'], 9)
        self.assertEqual((spider.n_events, spider.n_unknown), (1, 1))
        self.assertIs(out[-1], True)
        self.assertEqual(len(seeds('deal')), 1)          # 本頁最舊已越過窗口 → 不再排下一頁

    def test_today_stub_houses_are_known(self):
        from tests.helpers import write_stubs
        write_stubs(self, ['known1', 'ghost1'])
        spider = self.spider(lookback_days=2)
        events = [o for o in spider.parse_deal_and_stop(self.deal_response()) if not isinstance(o, bool)]
        self.assertEqual(sorted(e['vendor_house_id'] for e in events), ['ghost1', 'known1'])

    def test_parse_persists_next_page_while_window_not_exhausted(self):
        spider = self.spider(lookback_days=30)
        spider.persist_queue.gen_persist_request({'id': '1', 'name': '台北市', 'page': 1})
        list(spider.parse_deal_and_stop(self.deal_response()))
        self.assertEqual(sorted(s['page'] for s in seeds('deal')), [1, 2])


if __name__ == '__main__':
    unittest.main()
