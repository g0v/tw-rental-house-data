import os
import uuid
import scrapy
import traceback
from datetime import datetime, timedelta
from twisted.internet import threads
from django.db import connection
from django.utils import timezone
from rental.models import HouseTS, Vendor
from rental import models
from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestType
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

        if is_list:
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
        undone_requests = RequestTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
            # Ignore pending request since we will generate new one and rerun it anyway
            is_pending = False,
            vendor = self.vendor,
            request_type = self.request_type
        )[:1]

        return undone_requests.count() > 0
    
    def get_total_count(self):
        """Get the total number of requests in the queue."""
        total = RequestTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
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
        with connection.cursor() as cursor:
            sql = (
                'update request_ts set owner = %s where id = ('
                'select id from request_ts where year = %s and month = %s '
                'and day = %s and hour = %s and vendor_id = %s and request_type = %s '
                'and is_pending = %s and owner is null order by id limit 1 '
                'for update skip locked) and owner is null'
            )
            a = cursor.execute(sql, [
                self.spider_id,
                self.ts['y'],
                self.ts['m'],
                self.ts['d'],
                self.ts['h'],
                self.vendor.id,
                self.request_type.value,
                False
            ])

        next_row = RequestTS.objects.filter(
            year=self.ts['y'],
            month=self.ts['m'],
            day=self.ts['d'],
            hour=self.ts['h'],
            vendor=self.vendor,
            request_type=self.request_type,
            is_pending=False,
            owner=self.spider_id
        ).order_by('created')

        next_row = next_row.first()

        if next_row is None:
            return None

        next_row.is_pending = True
        next_row.save()
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

    def parser_wrapper(self, response):
        db_request = response.meta['db_request']
        db_request.last_status = response.status
        db_request.save()

        meta = response.meta.get('rental', {})

        try:
            for item in self.parse_response(response):
                if item is True:
                    db_request.delete()
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
