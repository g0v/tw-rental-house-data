'''deal591：走 591「已成交」列表產成交事件（#229，deals stage）。

591 自 2026 改版起 detail 頁成交即 404，成交只出現在 list?shType=clinch。
每縣市從第 1 頁倒序翻到 lookback 窗外即停（package 的 DealMixin 決定），
這裡負責：種子入 persist queue（DEAL 類型，與 list／detail 同一張表、
同一套 seeds==terminals 對帳）、相對成交日的基準日釘在 pipeline 日期、
只對 DB 已知的物件寫事件（未知＝刊登與成交都落在兩次爬取之間，只計數）。

    scrapy crawl deal591 -L INFO -a lookback_days=2        # 日跑
    scrapy crawl deal591 -L INFO -a lookback_days=12       # 回補
    scrapy crawl deal591 -L INFO -a target_cities=台北市
'''
from datetime import date

from scrapy import Request, signals
from scrapy_twrh.items import GenericHouseItem
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from rental.models import House
from crawlerrequest.enums import RequestType
from .persist_queue import PersistQueue


class Deal591Spider(Rental591Spider):
    name = 'deal591'

    def __init__(self, append=False, start_early=False, lookback_days=2, **kwargs):
        if isinstance(kwargs.get('target_cities'), str):
            kwargs['target_cities'] = kwargs['target_cities'].split(',')

        super().__init__(
            start_list=self.start_deal_from_persist_queue,
            deal_lookback_days=lookback_days,
            **kwargs
        )

        self.append = append == 'True' or append is True
        self.start_early = start_early == 'True' or start_early is True
        self.n_events = 0
        self.n_unknown = 0

        self.persist_queue = PersistQueue(
            vendor='591 租屋網',
            is_list=True,
            request_type=RequestType.DEAL,
            logger=self.logger,
            seed_parser=self.parse_seed,
            generate_request_args=self.gen_deal_request_args,
            parse_response=self.parse_deal_and_stop,
            start_early=self.start_early,
            spider=self
        )
        # 相對成交日（今日／昨日／N天前）的基準＝pipeline 釘的日期，
        # 與 queue 同源（TWRH_TARGET_DATE／--start-early），stage 不看時鐘
        ts = self.persist_queue.ts
        self.deal_base_date = date(ts['y'], ts['m'], ts['d'])

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super(Deal591Spider, cls).from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        return spider

    def spider_closed(self, spider=None):
        self.persist_queue.release_claims()
        self.persist_queue.progress_tracker.log_final()
        self.logger.info(
            '[deal] %d events written, %d for houses never seen (skipped), '
            '%d with unknown deal_time',
            self.n_events, self.n_unknown, self.deal_unknown_ages)

    def error_handler(self, failure):
        super().error_handler(failure)
        self.persist_queue.handle_errback(failure)

    def parse_seed(self, seed):
        if isinstance(seed, dict):
            return util.DealRequestMeta(**seed)
        return util.DealRequestMeta(*seed)

    def start_deal_from_persist_queue(self):
        for city in self.target_cities:
            # 同日重跑續走 queue、不重生種子；deals 不一定有 TS 產出，
            # 以 queue 本身判斷（--append 強制重生）
            if not self.append and self.persist_queue.has_seed(seed__id=city['id']):
                continue
            self.logger.info('[deal] seeding %s (lookback %d days, base %s)',
                             city['city'], self.deal_lookback_days, self.deal_base_date)
            self.persist_queue.gen_persist_request({
                'id': city['id'],
                'name': city['city'],
                'page': 1,
            })

        self.persist_queue.init_progress_tracking()

        while True:
            next_request = self.persist_queue.next_request()
            if next_request:
                yield next_request
            else:
                break

    def parse_deal_and_stop(self, response):
        items = []
        for item in self.default_parse_deal(response):
            if isinstance(item, Request):
                meta = item.meta['rental']
                if isinstance(meta, util.DealRequestMeta):
                    self.persist_queue.gen_persist_request(meta._asdict())
                continue
            items.append(item)

        events = [i for i in items if isinstance(i, GenericHouseItem)]
        known = set(House.objects.filter(
            vendor=self.persist_queue.vendor,
            vendor_house_id__in=[e['vendor_house_id'] for e in events],
        ).values_list('vendor_house_id', flat=True))

        for item in items:
            if isinstance(item, GenericHouseItem):
                if item['vendor_house_id'] not in known:
                    self.n_unknown += 1
                    continue
                self.n_events += 1
            yield item
        yield True
