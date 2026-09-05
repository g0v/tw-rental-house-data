import traceback
from datetime import date, timedelta
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from scrapy import signals
from rental.models import House, HouseTS
from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestType
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
                 consume_only=False, seed_only=False, stop_marker=None,
                 seed_mode='full', refresh_days=7, **kwargs):
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
        # dx 4-2：batch 額滿時 touch 這個檔，外層迴圈以檔案存在與否判斷是否
        # 重啟下一個 batch——取代 grep log 字串當控制流
        self.stop_marker = stop_marker
        # L-C：'full'＝全量 open（現行）；'diff'＝list diff 驅動的 skip 降頻。
        # 'new'＝只排從未抓過 detail 的 OPENED 物件（前緣掃描 devop/sweep.sh：
        # 同日多輪、不受 progress 檔的重生成防呆限制）
        self.seed_mode = seed_mode
        self.refresh_days = int(refresh_days)

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
        if self.stop_marker and self.persist_queue.is_batch_complete():
            with open(self.stop_marker, 'w'):
                pass

    def error_handler(self, failure):
        # 核心包的 errback 只留 log（vendor 中立）；1-1：dataset 側必寫
        # 終結狀態——failed／attempts＋1、達上限 dead，收工由 queuefinalize 對帳
        super().error_handler(failure)
        # 回傳補餵的 Request（errback 斷餵修正，見 persist_queue.handle_errback）
        return self.persist_queue.handle_errback(failure)

    def parse_seed(self, seed):
        # dx 4-3：種子是有 key 的 dict；list 為升級前殘留列（--date 重跑舊日）
        if isinstance(seed, dict):
            return util.DetailRequestMeta(**seed)
        return util.DetailRequestMeta(*seed)

    def gen_full_seeds(self):
        '''現行全量模式：所有 OPENED 房源都排 detail。'''
        query = House.objects.filter(
            deal_status = enums.DealStatusType.OPENED
        )

        # In append mode, only houses never detail-crawled. monthly_price
        # can't tell anymore — since the 2026 redesign the list page item
        # already carries the price, so it is never null for new houses.
        if self.append:
            query = query.filter(etc__detail_raw__isnull=True)

        return list(query.values_list('vendor_house_id', flat=True))

    def gen_new_seeds(self):
        '''前緣掃描用：OPENED 且 detail 從未爬過（detail_crawled_at 為空）。

        用 detail_crawled_at 而非 append 模式的 etc.detail_raw——D5 後 DB 不存 raw。
        '''
        ts = self.persist_queue.ts
        already = set(RequestTS.objects.filter(
            year=ts['y'], month=ts['m'], day=ts['d'], hour=ts['h'],
            vendor=self.persist_queue.vendor, request_type=RequestType.DETAIL,
        ).values_list('seed__id', flat=True))
        # 當日已有 detail 列者（含 dead）不重排：同日多輪 sweep 不能把
        # 重試計數歸零、也不製造重複列
        return [h for h in House.objects.filter(
            deal_status=enums.DealStatusType.OPENED,
            detail_crawled_at__isnull=True,
        ).values_list('vendor_house_id', flat=True) if h not in already]

    def gen_diff_seeds(self):
        '''L-C(6)(7)：list diff 驅動的 detail 種子（docs/dx-roadmap.md）。

        skip 謂詞＝在今日 list ∧ OPENED ∧ 指紋未變 ∧ 距上次 detail < N 天；
        不滿足者入 queue，狀態變更永遠由 detail 判定：

        - stale／新物件：detail 從未爬過或超過 refresh_days（週期強制刷新
          兜底 update_time 不跳的暗改；新物件 detail_crawled_at 為 null）
        - fingerprint：list 指紋（price/title）在上次 detail 之後變過
        - absent：連續 ≥2 天不在 list（L-B 重測：單日缺席是暫時抖動、
          立即重掃絕大多數現身，連續缺席判準才把誤殺壓到個位數）
        - returned：缺席後回到 list（含關閉後回列）且本輪未 detail 過
          （12h 窗口＝同輪 pipeline 防重排，production 單輪 < 6h）

        「在今日 list」以 HouseTS 該日 bucket 的 list_crawled_at 判定，
        與 TWRH_TARGET_DATE／--start-early 的日期分桶一致。
        '''
        ts = self.persist_queue.ts
        today = date(ts['y'], ts['m'], ts['d'])
        yesterday = today - timedelta(days=1)
        now = timezone.now()

        def list_ids(day):
            return set(HouseTS.objects.filter(
                year=day.year, month=day.month, day=day.day,
                list_crawled_at__isnull=False,
            ).values_list('vendor_house_id', flat=True))

        in_list_today = list_ids(today)
        in_list_yesterday = list_ids(yesterday)

        open_qs = House.objects.filter(deal_status=enums.DealStatusType.OPENED)
        open_ids = set(open_qs.values_list('vendor_house_id', flat=True))

        stale = set(open_qs.filter(
            Q(detail_crawled_at__isnull=True) |
            Q(detail_crawled_at__lt=now - timedelta(days=self.refresh_days))
        ).values_list('vendor_house_id', flat=True))

        fingerprint = set(open_qs.filter(
            detail_crawled_at__isnull=False,
            list_fingerprint_changed_at__gt=F('detail_crawled_at'),
        ).values_list('vendor_house_id', flat=True)) & in_list_today

        absent = open_ids - in_list_today - in_list_yesterday

        fresh_this_run = set(open_qs.filter(
            detail_crawled_at__gte=now - timedelta(hours=12),
        ).values_list('vendor_house_id', flat=True))
        returned = ((open_ids & in_list_today) - in_list_yesterday) - fresh_this_run

        seeds = stale | fingerprint | absent | returned
        skipped = len(open_ids & in_list_today) - len(seeds & in_list_today)
        self.logger.info(
            'diff seeds: stale/new %d, fingerprint %d, absent>=2d %d, '
            'returned %d -> union %d (open %d, in-list %d, skipped %d)',
            len(stale), len(fingerprint), len(absent), len(returned),
            len(seeds), len(open_ids), len(in_list_today), skipped)
        return sorted(seeds)

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
        elif not self.persist_queue.has_request() \
                and self.persist_queue.has_run_today() and self.seed_mode != 'new':
            # queue 耗盡 + 今天已跑過 = batch 重啟／同日重跑時的正常收尾，
            # 不是新的一天。少了這個判斷，恰好在 batch 邊界耗盡 queue 會觸發
            # 下面的全量重生成（2026-08-26 實測 55,943 筆）。seed_only 也適用
            # ——flow 續跑／orchestrate 同日重啟時 seed stage 不得重排全量
            # （seed_only 的首跑不受影響：generation 在 progress 檔建立之前）。
            # 若要同日強制重生成（例如 --date 重跑），先刪當日 logs/progress/*.detail.json。
            self.logger.info(
                'queue empty and progress file exists — resume with nothing to do')
        elif not self.persist_queue.has_request():
            if self.seed_mode == 'diff':
                house_ids = self.gen_diff_seeds()
            elif self.seed_mode == 'new':
                house_ids = self.gen_new_seeds()
            else:
                house_ids = self.gen_full_seeds()

            self.logger.info('generating request: {} (mode: {}, append: {})'.format(
                len(house_ids), self.seed_mode, self.append))

            with transaction.atomic():
                try:
                    for house_id in house_ids:
                        self.persist_queue.gen_persist_request({'id': house_id})
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
