import os
import uuid
import scrapy
import traceback
from datetime import datetime, timedelta
from twisted.internet import threads
from django.db import connection
from django.utils import timezone
from scrapy.spidermiddlewares.httperror import HttpError
from rental.models import HouseTS, Vendor
from rental import models
from crawlerrequest.models import RequestTS
from crawlerrequest.enums import (
    RequestType, RequestStatus, REQUEST_STATUS_ACTIVE, REQUEST_STATUS_CLAIMABLE)
from crawler import signals as twrh_signals
from .progress_tracker import ProgressTracker

class PersistQueue(object):

    def __init__(
        self,
        vendor,
        is_list,
        logger,
        seed_parser,
        generate_request_args,
        parse_response,
        log_interval=60,
        start_early=False,
        batch_size=0,
        spider=None,
        request_type=None,
        **kwargs
    ):
        super().__init__(**kwargs)

        # 熔斷需要 spider.crawler.signals 送 parse_success/parse_error（dx 2-1）
        self.spider = spider
        
        # Check for date override from environment
        override = os.environ.get('TWRH_TARGET_DATE')
        if override:
            target_time = datetime.strptime(override, '%Y-%m-%d')
            y = target_time.year
            m = target_time.month
            d = target_time.day
        elif start_early and timezone.localtime().hour >= 22:
            # If start_early is True and hour is >= 22, use tomorrow's date
            target_time = timezone.localtime() + timedelta(days=1)
            y = target_time.year
            m = target_time.month
            d = target_time.day
        else:
            y = models.current_year()
            m = models.current_month()
            d = models.current_day()

        h = models.current_stepped_hour()

        # 4-4：原為 class attribute，靠 `self.x -= 1` 隱式轉 instance 是 footgun
        self.queue_length = 30
        self.n_live_spider = 0
        # 1-1：failed 重試上限，達上限轉 dead（errback／parse error 都算）
        self.max_attempts = int(os.environ.get('TWRH_QUEUE_MAX_ATTEMPTS', 3))

        self.spider_id = str(uuid.uuid4())
        self.logger = logger
        self.seed_parser = seed_parser
        self.generate_request_args = generate_request_args
        self.parse_response = parse_response
        
        # Initialize progress tracker
        self.progress_tracker = ProgressTracker(logger, log_interval=log_interval)
        
        try:
            self.vendor = Vendor.objects.get(
                name = vendor
            )
        except Vendor.DoesNotExist:
            raise Exception('Vendor "{}" is not defined.'.format(vendor))

        # request_type 顯式優先（deals stage 等第三種類型）；is_list 為舊介面
        if request_type is not None:
            self.request_type = RequestType(request_type)
        elif is_list:
            self.request_type = RequestType.LIST
        else:
            self.request_type = RequestType.DETAIL

        self.batch_size = batch_size
        self.ts = {
            'y': y,
            'm': m,
            'd': d,
            'h': h
        }

    def send_signal(self, signal, **kwargs):
        crawler = getattr(self.spider, 'crawler', None)
        if crawler is not None:
            crawler.signals.send_catch_log(
                signal, spider=self.spider, **kwargs)

    def has_request(self):
        '''還有可認領的列嗎（pending／failed 且未達重試上限）。'''
        undone_requests = RequestTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
            status__in = REQUEST_STATUS_CLAIMABLE,
            attempts__lt = self.max_attempts,
            owner__isnull = True,
            vendor = self.vendor,
            request_type = self.request_type
        )[:1]

        return undone_requests.count() > 0

    def get_total_count(self):
        """剩餘工作量＝未終結列數（1-1 後終結列留存，不能再數全表）。"""
        total = RequestTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
            status__in = REQUEST_STATUS_ACTIVE,
            vendor = self.vendor,
            request_type = self.request_type
        ).count()
        return total
    
    def init_progress_tracking(self):
        """Initialize progress tracking with the current total count.

        For detail spiders, uses a file to persist overall progress across batches.
        For list spiders, uses simple in-memory tracking.
        """
        total = self.get_total_count()
        if self.request_type == RequestType.DETAIL:
            progress_file = self.progress_file_path()
            os.makedirs(os.path.dirname(progress_file), exist_ok=True)
            self.progress_tracker.init_overall(progress_file, total)
        else:
            self.progress_tracker.set_total(total)
        return total

    def progress_file_path(self):
        progress_dir = os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'logs', 'progress')
        return os.path.join(
            progress_dir,
            f"{self.ts['y']}-{self.ts['m']:02d}-{self.ts['d']:02d}.detail.json"
        )

    def has_run_today(self):
        """今天的 detail 是否已經跑過（progress 檔存在）。

        用途：區分「batch 重啟時 queue 恰好耗盡」與「今天還沒生成過種子」——
        兩者的 has_request() 都是 False，但前者重生成會把全台 open 房源
        再排一輪（2026-08-26 全量實測踩到）。
        """
        return os.path.exists(self.progress_file_path())

    def is_batch_complete(self):
        """Check if the batch limit has been reached."""
        return self.batch_size > 0 and self.progress_tracker.completed >= self.batch_size

    def has_record(self, **extra_filters):
        # extra_filters 讓 caller 縮小判斷範圍，例如 top_region=<city enum>
        # ——同一天可能分city多次啟動，不能因為別的城市有記錄就跳過生種子
        today_houses = HouseTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
            vendor = self.vendor,
            **extra_filters
        )[:1]

        return today_houses.count() > 0

    def has_seed(self, **seed_filters):
        '''當日此類型是否已生過種子（seed JSON 欄位過濾，如 seed__id=<city id>）。

        給不寫 HouseTS 的 stage（deals）判斷「同日重跑」：has_record 看的是
        TS，deals stage 不一定有產出（當天沒成交也是正常）。
        '''
        return RequestTS.objects.filter(
            year=self.ts['y'],
            month=self.ts['m'],
            day=self.ts['d'],
            hour=self.ts['h'],
            vendor=self.vendor,
            request_type=self.request_type,
            **seed_filters
        )[:1].count() > 0

    def release_claims(self):
        """行程收工時，把自己認領但未終結的列標 failed 放回 queue。

        不釋放就掛在死掉的 owner 上，誰也爬不到。多 task 並跑（2.5-3）下
        尤其關鍵：被擋而亡的 worker 放手後，換新 IP 的替補 task 才接得走。
        單機 go.sh 下等於讓下一個 batch 多一輪重試。1-1 後：released 列
        寫 failed（達 attempts 上限則 dead），永久性失敗沉澱為 dead、
        由 queuefinalize 對帳。
        """
        own_claims = RequestTS.objects.filter(
            year=self.ts['y'],
            month=self.ts['m'],
            day=self.ts['d'],
            hour=self.ts['h'],
            vendor=self.vendor,
            request_type=self.request_type,
            owner=self.spider_id,
            # 只放未終結的：DONE/DEAD 已收工（且 owner 已清，這裡是雙保險）
            status=RequestStatus.IN_FLIGHT,
        )
        dead = own_claims.filter(attempts__gte=self.max_attempts).update(
            owner=None, status=RequestStatus.DEAD, error='released:unfinished')
        released = own_claims.update(
            owner=None, status=RequestStatus.FAILED, error='released:unfinished')
        if released or dead:
            self.logger.info(
                'released {} unfinished claimed request(s) ({} dead)'.format(
                    released + dead, dead))
        return released + dead

    def gen_persist_request(self, seed):
        RequestTS.objects.create(
            year=self.ts['y'],
            month=self.ts['m'],
            day=self.ts['d'],
            hour=self.ts['h'],
            request_type=self.request_type,
            vendor=self.vendor,
            seed=seed
        )
        # Update progress tracker total when new requests are added
        self.progress_tracker.increment_total()

    def next_request(self):
        if self.n_live_spider >= self.queue_length:
            # At most self.queue_length in memory
            return None

        # #21：FOR UPDATE SKIP LOCKED 讓認領原子化——並發 session 的子查詢會
        # 各自跳過已被鎖定的列，不再搶到同一筆（2.5-3 多 task 並跑的前提）。
        # 外層再補 owner is null 當保險：即使子查詢在鎖釋放後重讀，也不會蓋掉
        # 別人已寫入的 owner。
        # 1-1：認領＝pending/failed → in_flight、attempts+1（原子累加）；
        # failed 排在新列之後（order by attempts），達上限的列不再認領。
        with connection.cursor() as cursor:
            sql = (
                'update request_ts set owner = %s, status = %s, '
                'attempts = attempts + 1 where id = ('
                'select id from request_ts where year = %s and month = %s '
                'and day = %s and hour = %s and vendor_id = %s and request_type = %s '
                'and status in (%s, %s) and attempts < %s and owner is null '
                'order by attempts, id limit 1 '
                'for update skip locked) and owner is null '
                'returning id'
            )
            cursor.execute(sql, [
                self.spider_id,
                int(RequestStatus.IN_FLIGHT),
                self.ts['y'],
                self.ts['m'],
                self.ts['d'],
                self.ts['h'],
                self.vendor.id,
                self.request_type.value,
                int(RequestStatus.PENDING),
                int(RequestStatus.FAILED),
                self.max_attempts,
            ])
            claimed = cursor.fetchone()

        if claimed is None:
            return None

        next_row = RequestTS.objects.get(id=claimed[0])
        self.n_live_spider += 1

        rental_meta = self.seed_parser(next_row.seed)

        request_args = {
            **self.generate_request_args(rental_meta),
            # overwrite callback directly, 
            # as we know where to find real parser
            'callback': self.parser_wrapper
        }

        if 'meta' not in request_args:
            request_args['meta'] = {
                'rental': rental_meta,
                'db_request': next_row
            }
        elif 'db_request' not in request_args['meta']:
            request_args['meta']['db_request'] = next_row

        return scrapy.Request(**request_args)

    def mark_failed(self, db_request, error):
        '''1-1：失敗必寫終結狀態——failed 可重試，達 attempts 上限轉 dead。'''
        db_request.error = (error or '')[:255] or None
        if db_request.attempts >= self.max_attempts:
            db_request.status = RequestStatus.DEAD
        else:
            db_request.status = RequestStatus.FAILED
        db_request.owner = None
        db_request.save()

    def handle_errback(self, failure):
        '''spider errback 的 DB 側：分類錯誤、寫終結狀態、釋放 in-memory 名額。

        403 全滅這類「spider 正常 finished 但整批 errback」的事故，
        從此在 queue 留下可對帳的 failed/dead 列，queuefinalize 當場紅，
        而不是等 statscheck 事後驗屍。
        '''
        request = getattr(failure, 'request', None)
        db_request = request.meta.get('db_request') if request else None
        if db_request is None:
            return
        if failure.check(HttpError):
            response = failure.value.response
            db_request.last_status = response.status
            error = 'http_{}'.format(response.status)
        else:
            error = failure.type.__name__
        self.mark_failed(db_request, error)
        # errback 的請求不會再進 parser_wrapper，名額在這裡釋放——
        # 舊制 errback 佔著 queue_length 名額不放，是「斷餵」的成因之一
        self.n_live_spider -= 1

    def parser_wrapper(self, response):
        db_request = response.meta['db_request']
        db_request.last_status = response.status
        db_request.save()

        meta = response.meta.get('rental', {})

        try:
            for item in self.parse_response(response):
                if item is True:
                    # 1-1：「刪列＝完成」廢除，完成寫顯式終結狀態。
                    # owner 必清：否則收工的 release_claims 會把 DONE 翻回 failed
                    db_request.status = RequestStatus.DONE
                    db_request.error = None
                    db_request.owner = None
                    db_request.save()
                    # Track progress after successful completion
                    self.progress_tracker.increment()
                    self.send_signal(twrh_signals.parse_success)
                else:
                    yield item
        except Exception as err:
            self.logger.error(
                'Parser error in {} when handle meta {}. [{}] - {:.128}'.format(
                    self.vendor.name,
                    meta,
                    response.status,
                    response.text
                )
            )
            traceback.print_exc()
            self.mark_failed(
                db_request, 'parse_error:{}'.format(type(err).__name__))
            self.send_signal(twrh_signals.parse_error, exception=err)

        self.n_live_spider -= 1

        if self.is_batch_complete():
            self.logger.info(
                'Batch limit reached (%d items), stopping to release memory...',
                self.batch_size
            )
            return

        # quick fix for concurrency issue
        mercy = 10
        while True:
            # 這個 generator 每次 yield 都會懸掛，item pipeline 是非同步的，
            # 所以觸頂前懸掛在迴圈中間的 wrapper 會在觸頂後恢復並繼續認領——
            # 迴圈內也要檢查，僅靠迴圈前那次檢查擋不住（2026-08-26 batch 13 實測：
            # 觸頂後仍多爬 2,559 筆，enqueue 全由懸掛中的補貨迴圈餵出）
            if self.is_batch_complete():
                break
            next_request = self.next_request()
            if next_request:
                yield next_request
            elif mercy < 0:
                break
            else:
                mercy -= 1
