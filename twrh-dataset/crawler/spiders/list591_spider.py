from scrapy import Request, signals
from scrapy_twrh.items import GenericHouseItem, RawHouseItem
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from rental.enums import TopRegionType
import os
from crawler.orm import House   # S6：house DB 回退才用得到，延遲載入
from rental import known
from rental.switches import house_db
from .persist_queue import PersistQueue
from .item_hygiene import strip_list_item

class List591Spider(Rental591Spider):
    name = 'list591'

    def __init__(self, append=False, start_early=False, frontier_pages=0, **kwargs):
        # scrapy -a target_cities=A,B 傳進來是字串，直接迭代會變成逐字比對
        if isinstance(kwargs.get('target_cities'), str):
            kwargs['target_cities'] = kwargs['target_cities'].split(',')

        super().__init__(
            start_list=self.start_list_from_persist_queue,
            **kwargs
        )

        self.append = append == 'True' or append == True
        self.start_early = start_early == 'True' or start_early == True
        # 前緣掃描（短命物件，#229 追查）：只走每縣市 list 的最前面幾頁——
        # 排序鍵是刊登時間，新刊登在最前面且連續——逐頁前進，整頁都是
        # DB 已知物件即收單；N＝每縣市頁數上限（runaway guard）。0＝關閉，
        # 走原本的全量翻頁。清晨全量之後每隔數小時跑一次，配 detail591
        # -a seed_mode=new 補抓新物件的 detail（devop/sweep.sh）。
        self.frontier_pages = int(frontier_pages)
        self.frontier_new = 0

        self.persist_queue = PersistQueue(
            vendor='591 租屋網',
            is_list=True,
            logger=self.logger,
            seed_parser=self.parse_seed,
            generate_request_args=self.gen_list_request_args,
            parse_response=self.parse_list_and_stop,
            start_early=self.start_early,
            spider=self
        )
    
    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super(List591Spider, cls).from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        return spider
    
    def spider_closed(self, spider=None):
        self.persist_queue.release_claims()
        self.persist_queue.progress_tracker.log_final()
        if self.frontier_pages:
            self.logger.info('[frontier] %d unseen houses discovered', self.frontier_new)

    def error_handler(self, failure):
        # 核心包的 errback 只留 log（vendor 中立）；1-1：dataset 側必寫
        # 終結狀態——failed／attempts＋1、達上限 dead，收工由 queuefinalize 對帳
        super().error_handler(failure)
        # 回傳補餵的 Request（errback 斷餵修正，見 persist_queue.handle_errback）
        return self.persist_queue.handle_errback(failure)

    def parse_seed (self, seed):
        # dx 4-3：種子是有 key 的 dict；list 為升級前殘留列（--date 重跑舊日）
        if isinstance(seed, dict):
            return util.ListRequestMeta(**seed)
        return util.ListRequestMeta(*seed)

    def ran_today(self, city):
        '''同日重跑不重生種子。DB 時代看 HouseTS 當日有沒有這個縣市的列；S3b 後看當日
        list 種子檔有沒有這個縣市（種子在＝今天排過，沒爬完的由 queue 自己續）。'''
        if house_db():
            return self.persist_queue.has_record(top_region=TopRegionType[city['city']])
        return self.persist_queue.has_seed(seed__id=city['id'])

    def start_list_from_persist_queue (self):
        # In append mode, always regenerate seeds.
        # In normal mode, generate per city — has_record() must be scoped to the
        # city, or a same-day run for city B is silently skipped after city A.
        for city in self.target_cities:
            # 前緣掃描永遠重生種子（同日多輪是它的本意）
            if not self.append and not self.frontier_pages and self.ran_today(city):
                continue
            self.logger.info('Generating initial requests for {} (append mode: {})'.format(
                city['city'], self.append))
            # let's do BFS
            # dx 4-3：seed 用有 key 的 dict——位置參數改欄位順序會靜默錯位
            self.persist_queue.gen_persist_request({
                'id': city['id'],
                'name': city['city'],
                'page': 0,
            })
        
        # Initialize progress tracking
        self.persist_queue.init_progress_tracking()

        while True:
            next_request = self.persist_queue.next_request()
            if next_request:
                yield next_request
            else:
                break

    def parse_list_and_stop(self, response):
        if self.frontier_pages:
            yield from self.parse_frontier_page(response)
            return
        for item in self.default_parse_list(response):
            if isinstance(item, Request):
                meta = item.meta['rental']
                if isinstance(meta, util.ListRequestMeta):
                    self.persist_queue.gen_persist_request(meta._asdict())
                continue
            else:
                if type(item) is GenericHouseItem:
                    strip_list_item(item)
                yield item
        yield True

    def known_houses(self):
        if getattr(self, '_known', None) is None:
            pq = self.persist_queue
            self._known = known.load(pq.short, pq.date_str, os.environ.get('TWRH_RAW_BUCKET') or None)
            self.logger.info('[frontier] known houses: %d (latest %s + stubs of %s)',
                             len(self._known.ids), self._known.base_date, self._known.stub_days)
        return self._known

    def parse_frontier_page(self, response):
        '''前緣模式：不接受 package 的頁範圍展開與前緣探測，翻頁自己決定。

        先把整頁 item 收齊、查 DB 哪些是沒見過的，再 yield item——pipeline
        是同步的，先 yield 會讓本頁物件立刻變成「已知」而誤判收單。
        '''
        meta = response.meta['rental']
        items = [item for item in self.default_parse_list(response)
                 if not isinstance(item, Request)]
        ids = [item['house_id'] for item in items if isinstance(item, RawHouseItem)]
        if house_db():
            seen = set(House.objects.filter(
                vendor=self.persist_queue.vendor, vendor_house_id__in=ids,
            ).values_list('vendor_house_id', flat=True))
            unseen = [h for h in ids if h not in seen]
        else:
            # S3b：已知物件＝總表(昨日)＋今日各輪 stub＋本行程前面幾頁剛看到的
            # （DB 時代是 pipeline 同步寫入讓前頁的戶立刻變已知，這裡自己記）
            seen = self.known_houses()
            unseen = [h for h in ids if h not in seen]
            for h in ids:
                seen.add(h)
        self.frontier_new += len(unseen)
        self.logger.info('[frontier] %s page %d: %d items, %d unseen',
                         meta.name, meta.page + 1, len(ids), len(unseen))
        for item in items:
            if type(item) is GenericHouseItem:
                strip_list_item(item)
            yield item
        if unseen and ids and meta.page + 1 < self.frontier_pages:
            self.persist_queue.gen_persist_request({
                'id': meta.id, 'name': meta.name, 'page': meta.page + 1})
        elif unseen and ids:
            self.logger.warning('[frontier] %s hit page cap %d with unseen items left',
                                meta.name, self.frontier_pages)
        yield True
