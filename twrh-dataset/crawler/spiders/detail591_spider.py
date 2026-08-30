import traceback
from django.db import transaction
from scrapy import signals
from rental.models import House
from rental import enums
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from .persist_queue import PersistQueue

class Detail591Spider(Rental591Spider):
    name = "detail591"

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'rotating_proxies.middlewares.RotatingProxyMiddleware': None,
            'rotating_proxies.middlewares.BanDetectionMiddleware': None,
        },
    }

    def __init__(self, append=False, start_early=False, batch_size=0,
                 consume_only=False, seed_only=False, **kwargs):
        super().__init__(
            start_list=self.start_detail_requests,
            **kwargs
        )

        self.append = append == 'True' or append == True
        self.start_early = start_early == 'True' or start_early == True
        self.batch_size = int(batch_size)
        # 2.5-3 多 task worker：只消化 queue、絕不生種子——種子由單一 primary 生，
        # N 個 worker 同日並發走到重生成分支會 race 出整批重複列（create 非 upsert）
        self.consume_only = consume_only == 'True' or consume_only == True
        # 2.5-3 primary：只生種子、不爬——orchestrate 在 list 後、開 worker 前跑，
        # 與 consume_only 成對（首航實測：全 worker 都 consume_only 時沒人生種子）
        self.seed_only = seed_only == 'True' or seed_only == True

        self.persist_queue = PersistQueue(
            vendor='591 租屋網',
            is_list=False,
            logger=self.logger,
            seed_parser=self.parse_seed,
            generate_request_args=self.gen_detail_request_args,
            parse_response=self.parse_detail_and_done,
            start_early=self.start_early,
            batch_size=self.batch_size,
            spider=self
        )
    
    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super(Detail591Spider, cls).from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        return spider
    
    def spider_closed(self, spider=None):
        self.persist_queue.release_claims()
        self.persist_queue.progress_tracker.log_final()

    def parse_seed(self, seed):
        return util.DetailRequestMeta(*seed)

    def parse_detail_and_done (self, response):
        for item in self.default_parse_detail(response):
            if item:
                yield item
        yield True

    def start_detail_requests(self):

        if self.consume_only:
            self.logger.info('consume-only mode: skip seed generation')
        elif self.seed_only and self.persist_queue.has_request():
            # 同日重跑：種子已在，不重生成（gen_persist_request 是 create 非 upsert）
            self.logger.info('seed-only mode: queue not empty, nothing to generate')
        elif not self.persist_queue.has_request() and not self.seed_only \
                and self.persist_queue.has_run_today():
            # queue 耗盡 + 今天已跑過 = go.sh batch 重啟時的正常收尾，不是新的一天。
            # 少了這個判斷，恰好在 batch 邊界耗盡 queue 會觸發下面的全量重生成，
            # 把全台 open 房源再排一輪（2026-08-26 實測 55,943 筆）。
            # 若要同日強制重生成（例如 --date 重跑），先刪當日 logs/progress/*.detail.json。
            self.logger.info(
                'queue empty and progress file exists — resume with nothing to do')
        elif not self.persist_queue.has_request():
            # find all opened houses and crawl all of them
            query = House.objects.filter(
                deal_status = enums.DealStatusType.OPENED
            )
            
            # In append mode, only houses never detail-crawled. monthly_price
            # can't tell anymore — since the 2026 redesign the list page item
            # already carries the price, so it is never null for new houses.
            if self.append:
                query = query.filter(etc__detail_raw__isnull=True)
                
            houses = query.values('vendor_house_id')

            total = houses.count()
            self.logger.info('generating request: {} (append mode: {})'.format(total, self.append))

            with transaction.atomic():
                try:
                    for house in houses:
                        self.persist_queue.gen_persist_request([house['vendor_house_id']])
                except:
                    traceback.print_exc()
        
        # Initialize progress tracking
        total = self.persist_queue.init_progress_tracking()

        if self.seed_only:
            # 種子已就緒，爬取交給 consume_only worker 群
            self.logger.info(
                'seed-only mode: {} requests in queue, exit without crawling'.format(total))
            return

        # quick fix for concurrency issue
        mercy = 10
        while True:
            # start_requests 是被 engine 惰性消費的 generator，batch 額滿後若不在這裡
            # 一起停，parser_wrapper 的早退會讓這條路變成唯一餵食者、把整條 queue 跑完
            # （2026-08-26 全量實測踩到）
            if self.persist_queue.is_batch_complete():
                break
            next_request = self.persist_queue.next_request()
            if next_request:
                yield next_request
            elif mercy < 0:
                break
            else:
                mercy -= 1
