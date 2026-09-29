import os
import traceback
from datetime import date, timedelta
from rental import tz as timezone   # S6：無 Django（同介面）
from scrapy import signals
from rental import enums
from scrapy_twrh.items import GenericHouseItem
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from rental import artifacts, seeding, known
from .persist_queue import PersistQueue
from .item_hygiene import strip_detail_item

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
                 seed_mode='full', refresh_days=7, refresh_jitter=0, **kwargs):
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
        # stale 門檻 per-house 抖動（±N 天，house_id 雜湊決定），攤平 bootstrap 回波；
        # 與 rental.seeding 的純函數同一個算式，seedcheck 兩軌才對得上
        self.refresh_jitter = int(refresh_jitter)

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

    def load_known(self):
        pq = self.persist_queue
        k = known.load(pq.short, pq.date_str, os.environ.get('TWRH_RAW_BUCKET') or None)
        self.logger.info('known houses: %d (latest %s + stubs of %s)',
                         len(k.ids), k.base_date, k.stub_days)
        return k

    def gen_full_seeds_from_files(self):
        '''S3b 的全量模式：總表(昨日)＋今日 stub 裡所有 OPENED 的戶；append＝其中從未 detail 的。'''
        k = self.load_known()
        return sorted(hid for hid, st in k.state.items()
                      if st.open and (not self.append or st.detail_crawled_at is None))

    def gen_full_seeds(self):
        '''全量模式：總表(昨日)＋今日 stub 裡所有 OPENED 的戶；append＝其中從未 detail 的。'''
        return self.gen_full_seeds_from_files()

    def gen_snapshot_seeds(self):
        '''diff 種子（L-C list-diff 降頻，docs/dx-roadmap.md）：判準讀檔案（今日 list stub＋
        昨日 snapshot 的 carry 欄），純函數 `seeding.select_seeds`：stale／新物件、指紋變、
        連續 ≥2 天缺席、回列四類聯集。材料不齊回 None → 呼叫端排全量（多爬一晚，不漏）。
        '''
        ts = self.persist_queue.ts
        today = date(ts['y'], ts['m'], ts['d'])
        now = timezone.now()
        result, meta = seeding.seeds_from_files(
            self.persist_queue.short, today, now,
            refresh_days=self.refresh_days,
            refresh_jitter_days=self.refresh_jitter,
            bucket=os.environ.get('TWRH_RAW_BUCKET'))
        if result is None:
            self.logger.warning(
                'snapshot seeds unavailable (%s) — full seeds instead',
                meta.get('reason'))
            return None
        self.logger.info(
            'snapshot seeds: stale/new %d, fingerprint %d, absent>=2d %d, '
            'returned %d -> union %d (open %d, in-list %d, skipped %d; %s)',
            len(result.stale), len(result.fingerprint), len(result.absent),
            len(result.returned), len(result.seeds), result.n_open,
            result.n_in_list, result.skipped, meta)
        seeding.write_seed_stamp(today, now, {
            'stale': len(result.stale), 'fingerprint': len(result.fingerprint),
            'absent': len(result.absent), 'returned': len(result.returned)},
            len(result.seeds))
        return sorted(result.seeds)

    def gen_new_seeds(self):
        '''前緣掃描用：今日在列（list stub 分區）∧ OPENED ∧ detail 從未爬過，與
        seeding.select_new_seeds 同義。狀態來自總表(昨日)＋今日 stub（不在總表的＝新戶：
        open、從未 detail）。今天稍早才 detail 過的戶總表還不知道，靠當日 detail 種子擋掉——
        同日多輪 sweep 不能把重試計數歸零、也不製造重複項。
        '''
        pq = self.persist_queue
        already = pq.seed_ids_today()
        k = self.load_known()
        stubs = list(artifacts.read_list_stubs(
            pq.short, pq.date_str, os.environ.get('TWRH_RAW_BUCKET') or None))
        self.logger.info('new seeds: {} stubs today'.format(len(stubs)))
        return sorted(h for h in seeding.select_new_seeds(stubs, k.state) if h not in already)

    def parse_detail_and_done (self, response):
        for item in self.default_parse_detail(response):
            if item:
                if type(item) is GenericHouseItem:
                    strip_detail_item(item)
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
                house_ids = self.gen_snapshot_seeds()
                if house_ids is None:
                    # 材料不齊（昨日 snapshot／今日 stub 缺）就排全量——多爬一晚，不漏；
                    # gen_snapshot_seeds 已經把原因 log 成 warning
                    self.logger.error('snapshot seeds unavailable — full seeds')
                    house_ids = self.gen_full_seeds_from_files()
            elif self.seed_mode == 'new':
                house_ids = self.gen_new_seeds()
            else:
                house_ids = self.gen_full_seeds()

            self.logger.info('generating request: {} (mode: {}, append: {})'.format(
                len(house_ids), self.seed_mode, self.append))

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
