'''B 層測試：queue 語意矩陣（architecture-roadmap 2-3，與 1-1 同做）。

歷史上 bug 密度最高的共用件是 persist_queue——認領 race（#21）、batch 觸頂
後繼續爬（2026-08-26）、queue 恰好耗盡誤觸全量重生成（2026-08-26）、
errback 列無人釋放。這裡把這些語意鎖成測試，作為 1-1 狀態機重構的安全網。

跑法（需 PostGIS，吃 .env 的 TWRH_DB_*）：
    poetry run python django/manage.py test crawlerrequest

「完成／失敗」的儲存語意集中在 assert_* helper——1-1 把「刪列＝完成」
換成顯式終結狀態時，矩陣本身不動，只改 helper。
'''
import os
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, TransactionTestCase
from django.db import connection
from django.utils import timezone

# crawler/ 在 repo 的 twrh-dataset 根目錄（不是 Django app），手動補 path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scrapy  # noqa: E402
from scrapy.http import TextResponse  # noqa: E402

from crawlerrequest.models import RequestTS  # noqa: E402
from crawlerrequest.enums import RequestType, RequestStatus  # noqa: E402
from rental.models import House, HouseTS, Vendor  # noqa: E402
from rental import enums  # noqa: E402
from crawler.spiders.persist_queue import PersistQueue  # noqa: E402

import logging  # noqa: E402

TEST_DATE = '2026-01-15'
VENDOR_NAME = '591 租屋網'


def make_queue(is_list=False, batch_size=0, parse_response=None, **kwargs):
    '''最小可用的 PersistQueue，不掛 spider（send_signal 為 no-op）。'''
    return PersistQueue(
        vendor=VENDOR_NAME,
        is_list=is_list,
        logger=logging.getLogger('test'),
        seed_parser=lambda seed: seed,
        generate_request_args=lambda meta: {
            'url': 'https://example.com/{}'.format(meta.get('id', 'x')),
            'meta': {'rental': meta},
        },
        parse_response=parse_response or (lambda response: iter([True])),
        batch_size=batch_size,
        **kwargs
    )


def make_response(db_request, status=200, body=b'ok'):
    '''模擬 engine 回呼 parser_wrapper 時的 response（meta 掛 db_request）。'''
    request = scrapy.Request(
        url='https://example.com/r',
        meta={'rental': {'id': 'r'}, 'db_request': db_request},
    )
    return TextResponse(
        url=request.url, status=status, body=body, request=request,
        encoding='utf-8',
    )


class QueueTestMixin:
    '''固定日期＋通用 helper。終結語意的斷言集中在 assert_*。'''

    fixtures = ['vendors']

    def setUp(self):
        super().setUp()
        self._old_target_date = os.environ.get('TWRH_TARGET_DATE')
        os.environ['TWRH_TARGET_DATE'] = TEST_DATE
        # 4e 雙軌：PersistQueue 會同步寫檔案 queue，測試一律導到暫存目錄，
        # 不污染 repo 的 artifacts/（子類另設 TWRH_ARTIFACT_DIR 者以子類為準）
        import tempfile
        self._artifact_tmp = tempfile.mkdtemp(prefix='twrh-test-artifacts-')
        self._artifact_env = mock.patch.dict(
            os.environ, {'TWRH_ARTIFACT_DIR': self._artifact_tmp})
        self._artifact_env.start()

    def tearDown(self):
        import shutil
        self._artifact_env.stop()
        shutil.rmtree(self._artifact_tmp, ignore_errors=True)
        if self._old_target_date is None:
            os.environ.pop('TWRH_TARGET_DATE', None)
        else:
            os.environ['TWRH_TARGET_DATE'] = self._old_target_date
        super().tearDown()

    # --- 終結語意斷言（1-1 狀態機版；舊制為「刪列＝完成」） ---

    def assert_completed(self, row_id):
        '''完成＝列留存、status=DONE、owner 已清。'''
        row = RequestTS.objects.get(id=row_id)
        self.assertEqual(row.status, RequestStatus.DONE)
        self.assertIsNone(row.owner)

    def assert_retriable_failure(self, row_id, error=None):
        '''失敗列仍在、status=FAILED、可被之後的認領撿走。'''
        row = RequestTS.objects.get(id=row_id)
        self.assertEqual(row.status, RequestStatus.FAILED)
        self.assertIsNone(row.owner)
        if error is not None:
            self.assertEqual(row.error, error)


class GenAndClaimTests(QueueTestMixin, TestCase):
    '''種子建立與認領：owner／is_pending／範圍界定。'''

    def test_gen_persist_request_creates_unclaimed_row(self):
        q = make_queue()
        q.gen_persist_request({'id': 'h1'})

        row = RequestTS.objects.get()
        self.assertEqual(row.seed, {'id': 'h1'})
        self.assertEqual(row.request_type, RequestType.DETAIL)
        self.assertEqual((row.year, row.month, row.day), (2026, 1, 15))
        self.assertIsNone(row.owner)
        self.assertEqual(row.status, RequestStatus.PENDING)
        self.assertEqual(row.attempts, 0)
        self.assertEqual(q.progress_tracker.total, 1)
        self.assertTrue(q.has_request())

    def test_next_request_claims_exactly_one(self):
        q = make_queue()
        q.gen_persist_request({'id': 'h1'})
        q.gen_persist_request({'id': 'h2'})

        request = q.next_request()

        self.assertIsInstance(request, scrapy.Request)
        claimed = request.meta['db_request']
        claimed.refresh_from_db()
        self.assertEqual(claimed.owner, q.spider_id)
        self.assertEqual(claimed.status, RequestStatus.IN_FLIGHT)
        self.assertEqual(claimed.attempts, 1)
        self.assertEqual(q.n_live_spider, 1)
        # 另一列仍是可認領狀態
        other = RequestTS.objects.exclude(id=claimed.id).get()
        self.assertIsNone(other.owner)

    def test_next_request_returns_none_on_empty_queue(self):
        q = make_queue()
        self.assertIsNone(q.next_request())

    def test_next_request_skips_rows_claimed_by_others(self):
        q = make_queue()
        q.gen_persist_request({'id': 'h1'})
        RequestTS.objects.update(
            owner='someone-else', status=RequestStatus.IN_FLIGHT)

        self.assertIsNone(q.next_request())

    def test_two_queues_claim_distinct_rows(self):
        q1 = make_queue()
        q2 = make_queue()
        q1.gen_persist_request({'id': 'h1'})
        q1.gen_persist_request({'id': 'h2'})

        r1 = q1.next_request()
        r2 = q2.next_request()

        self.assertNotEqual(
            r1.meta['db_request'].id, r2.meta['db_request'].id)

    def test_queue_length_caps_in_memory_requests(self):
        q = make_queue()
        q.gen_persist_request({'id': 'h1'})
        q.n_live_spider = q.queue_length

        self.assertIsNone(q.next_request())
        # 沒有列被偷偷認領
        self.assertFalse(
            RequestTS.objects.filter(owner__isnull=False).exists())

    def test_claim_scoped_to_date_vendor_and_type(self):
        q = make_queue()
        vendor = Vendor.objects.get(name=VENDOR_NAME)
        # 昨天的殘留列
        RequestTS.objects.create(
            year=2026, month=1, day=14, hour=0,
            request_type=RequestType.DETAIL, vendor=vendor, seed={'id': 'old'})
        # 同日但另一型
        RequestTS.objects.create(
            year=2026, month=1, day=15, hour=0,
            request_type=RequestType.LIST, vendor=vendor, seed={'id': 'list'})

        self.assertIsNone(q.next_request())
        self.assertFalse(q.has_request())


class ReleaseClaimsTests(QueueTestMixin, TestCase):
    '''收工釋放：只放自己的、不碰別人的（多 task 並跑的前提）。'''

    def test_release_only_own_claims(self):
        q1 = make_queue()
        q2 = make_queue()
        q1.gen_persist_request({'id': 'h1'})
        q1.gen_persist_request({'id': 'h2'})
        r1 = q1.next_request()
        r2 = q2.next_request()

        released = q1.release_claims()

        self.assertEqual(released, 1)
        self.assert_retriable_failure(
            r1.meta['db_request'].id, error='released:unfinished')
        other = RequestTS.objects.get(id=r2.meta['db_request'].id)
        self.assertEqual(other.owner, q2.spider_id)
        self.assertEqual(other.status, RequestStatus.IN_FLIGHT)

    def test_released_row_is_claimable_again(self):
        q1 = make_queue()
        q1.gen_persist_request({'id': 'h1'})
        q1.next_request()
        q1.release_claims()

        q2 = make_queue()
        request = q2.next_request()
        self.assertIsNotNone(request)
        self.assertEqual(request.meta['db_request'].owner, q2.spider_id)


class ParserWrapperTests(QueueTestMixin, TestCase):
    '''完成／解析失敗／batch 觸頂的儲存語意。'''

    def _claim_one(self, q, seed_id='h1'):
        q.gen_persist_request({'id': seed_id})
        return q.next_request().meta['db_request']

    def test_success_terminalizes_row(self):
        q = make_queue(batch_size=1)  # batch=1：完成後不進補貨迴圈
        row = self._claim_one(q)

        list(q.parser_wrapper(make_response(row)))

        self.assert_completed(row.id)
        self.assertEqual(q.progress_tracker.completed, 1)
        self.assertEqual(q.n_live_spider, 0)

    @staticmethod
    def exploding_parser(response):
        raise ValueError('boom')
        yield  # pragma: no cover

    def test_parse_error_marks_failed_and_retries_in_run(self):
        q = make_queue(batch_size=5, parse_response=self.exploding_parser)
        row = self._claim_one(q)

        yielded = list(q.parser_wrapper(make_response(row)))

        # 失敗列當場標 failed；同一輪的補貨迴圈立即重新認領重試
        followups = [r for r in yielded if isinstance(r, scrapy.Request)]
        self.assertEqual(len(followups), 1)
        self.assertEqual(followups[0].meta['db_request'].id, row.id)
        row.refresh_from_db()
        self.assertEqual(row.status, RequestStatus.IN_FLIGHT)
        self.assertEqual(row.attempts, 2)
        self.assertEqual(q.progress_tracker.completed, 0)

    def test_parse_error_at_max_attempts_goes_dead(self):
        q = make_queue(batch_size=5, parse_response=self.exploding_parser)
        q.max_attempts = 1
        row = self._claim_one(q)

        yielded = list(q.parser_wrapper(make_response(row)))

        self.assertEqual(
            [r for r in yielded if isinstance(r, scrapy.Request)], [])
        row.refresh_from_db()
        self.assertEqual(row.status, RequestStatus.DEAD)
        self.assertEqual(row.error, 'parse_error:ValueError')
        self.assertEqual(q.release_claims(), 0)

    def test_last_status_recorded(self):
        q = make_queue(batch_size=1)
        row = self._claim_one(q)

        list(q.parser_wrapper(make_response(row, status=404)))

        # 現制成功路徑會刪列，last_status 只在失敗列上看得到；
        # 這裡用失敗 parser 驗證寫入
        q2 = make_queue(batch_size=1, parse_response=lambda r: iter([]))
        row2 = self._claim_one(q2)
        list(q2.parser_wrapper(make_response(row2, status=403)))
        row2.refresh_from_db()
        self.assertEqual(row2.last_status, 403)

    def test_batch_limit_stops_replenishment(self):
        q = make_queue(batch_size=1)
        row1 = self._claim_one(q, 'h1')
        q.gen_persist_request({'id': 'h2'})  # 排隊中、觸頂後不應被認領

        yielded = list(q.parser_wrapper(make_response(row1)))

        self.assertTrue(q.is_batch_complete())
        self.assertEqual(
            [r for r in yielded if isinstance(r, scrapy.Request)], [])
        leftover = RequestTS.objects.get(seed={'id': 'h2'})
        self.assertIsNone(leftover.owner)

    def test_suspended_replenish_loop_stops_after_batch_limit(self):
        '''補貨迴圈懸掛在 yield 中間、恢復時已觸頂 → 不得繼續認領
        （2026-08-26 batch 13 實測：觸頂後多爬 2,559 筆的機制）。'''
        q = make_queue(batch_size=2)
        row1 = self._claim_one(q, 'h1')
        row2 = self._claim_one(q, 'h2')
        q.gen_persist_request({'id': 'h3'})
        q.gen_persist_request({'id': 'h4'})

        # 完成 h1（1/2），補貨迴圈 yield 出 h3 的請求後懸掛
        gen1 = q.parser_wrapper(make_response(row1))
        first_refill = next(gen1)
        self.assertEqual(first_refill.meta['db_request'].seed, {'id': 'h3'})
        # 完成 h2（2/2）→ 觸頂
        list(q.parser_wrapper(make_response(row2)))
        self.assertTrue(q.is_batch_complete())
        # 恢復懸掛中的 gen1：不得再把 h4 認領出來
        remainder = list(gen1)

        self.assertEqual(
            [r for r in remainder if isinstance(r, scrapy.Request)], [])
        leftover = RequestTS.objects.get(seed={'id': 'h4'})
        self.assertIsNone(leftover.owner)

    def test_below_batch_limit_replenishes_from_queue(self):
        q = make_queue(batch_size=5)
        row1 = self._claim_one(q, 'h1')
        q.gen_persist_request({'id': 'h2'})

        yielded = list(q.parser_wrapper(make_response(row1)))

        followups = [r for r in yielded if isinstance(r, scrapy.Request)]
        self.assertEqual(len(followups), 1)
        self.assertEqual(followups[0].meta['db_request'].seed, {'id': 'h2'})


class SeedMatrixTests(QueueTestMixin, TestCase):
    '''detail 種子矩陣：full／append／diff 四類（stale／指紋／缺席／回列）。'''

    def setUp(self):
        super().setUp()
        # 種子謂詞混用 DB 時間（timezone.now）與 queue 日期，測試日期釘在今天
        # 才能讓 refresh_days 這類 timedelta 條件對得上
        self.today = timezone.localtime().date()
        os.environ['TWRH_TARGET_DATE'] = self.today.isoformat()
        self.vendor = Vendor.objects.get(name=VENDOR_NAME)
        # spider 建構會在 logs/progress 外的路徑讀寫，測試不落地
        from crawler.spiders.detail591_spider import Detail591Spider
        self.spider_cls = Detail591Spider

    def make_house(self, hid, deal_status=enums.DealStatusType.OPENED, **kwargs):
        return House.objects.create(
            vendor=self.vendor, vendor_house_id=hid,
            deal_status=deal_status, **kwargs)

    def put_in_list(self, hid, day):
        HouseTS.objects.create(
            vendor=self.vendor, vendor_house_id=hid,
            year=day.year, month=day.month, day=day.day, hour=0,
            list_crawled_at=timezone.now())

    def make_spider(self, **kwargs):
        return self.spider_cls(**kwargs)

    def test_full_mode_seeds_all_opened(self):
        self.make_house('open1')
        self.make_house('open2')
        self.make_house('dealt', deal_status=enums.DealStatusType.DEAL)

        spider = self.make_spider()
        self.assertEqual(
            sorted(spider.gen_full_seeds()), ['open1', 'open2'])

    def test_diff_mode_four_seed_classes_and_skip(self):
        now = timezone.now()
        today = self.today
        yesterday = today - timedelta(days=1)

        # stale：超過 refresh_days 沒 detail
        self.make_house('stale', detail_crawled_at=now - timedelta(days=8))
        self.put_in_list('stale', today)
        # new：從未 detail 過
        self.make_house('new')
        self.put_in_list('new', today)
        # fingerprint：上次 detail 之後 list 指紋變了，且在今日 list
        self.make_house(
            'fp', detail_crawled_at=now - timedelta(days=2),
            list_fingerprint_changed_at=now - timedelta(days=1))
        self.put_in_list('fp', today)
        # absent：連續兩天不在 list
        self.make_house('absent', detail_crawled_at=now - timedelta(days=2))
        # returned：今日回列、昨日缺席、且本輪沒 detail 過
        self.make_house('returned', detail_crawled_at=now - timedelta(days=2))
        self.put_in_list('returned', today)
        # skip：在今日 list、指紋沒變、剛 detail 過
        self.make_house('skip', detail_crawled_at=now - timedelta(days=2))
        self.put_in_list('skip', today)
        self.put_in_list('skip', yesterday)
        # 昨日在列的 returned 對照組：昨天有出現就不算回列
        self.put_in_list('returned_ctrl_yesterday', yesterday)
        self.make_house(
            'returned_ctrl_yesterday',
            detail_crawled_at=now - timedelta(days=2))
        self.put_in_list('returned_ctrl_yesterday', today)

        spider = self.make_spider(seed_mode='diff', refresh_days=7)
        seeds = spider.gen_diff_seeds()

        self.assertEqual(
            sorted(seeds), ['absent', 'fp', 'new', 'returned', 'stale'])

    def test_refresh_jitter_matches_pure_function_per_house(self):
        '''抖動後 DB 判準與純函數 is_stale 逐戶一致；門檻落在 refresh±jitter 內且有分散。'''
        from rental import seeding
        now = timezone.now()
        ids = ['h{:03d}'.format(i) for i in range(60)]
        for i, hid in enumerate(ids):
            # 上次 detail 分佈在 4.75～9.75 天前（避開整數天邊界：spider 內的 now 晚幾毫秒）
            self.make_house(hid, detail_crawled_at=now - timedelta(days=4.75 + (i % 11) * 0.5))
            self.put_in_list(hid, self.today)
            self.put_in_list(hid, self.today - timedelta(days=1))
        spider = self.make_spider(seed_mode='diff', refresh_days=7, refresh_jitter=2)
        db_seeds = set(spider.gen_diff_seeds())
        expected = {hid for hid in ids if seeding.is_stale(
            hid, House.objects.get(vendor_house_id=hid).detail_crawled_at, now, 7, 2)}
        self.assertEqual(db_seeds, expected)
        thresholds = {seeding.refresh_days_for(hid, 7, 2) for hid in ids}
        self.assertTrue(thresholds <= {5, 6, 7, 8, 9} and len(thresholds) >= 4)
        self.assertEqual(seeding.refresh_days_for('h001', 7, 0), 7)
        # 無抖動＝舊制：門檻恰為 7 天
        plain = set(self.make_spider(seed_mode='diff', refresh_days=7).gen_diff_seeds())
        self.assertEqual(plain, {hid for hid in ids if
                                 House.objects.get(vendor_house_id=hid).detail_crawled_at < now - timedelta(days=7)})

    def test_diff_seed_leaves_now_stamp_for_seedcheck(self):
        '''spider 把算 stale 用的 now 與四類計數留在 logs/progress/<date>.seed.json；
        seedcheck 讀同一個 now（釘 RequestTS.created 仍晚幾分鐘：2026-09-12 only_pure 23）。'''
        import tempfile
        from unittest import mock
        from rental import seeding
        self.make_house('h1', detail_crawled_at=timezone.now() - timedelta(days=30))
        self.put_in_list('h1', self.today)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {'TWRH_PROGRESS_DIR': tmp}):
            before = timezone.now()
            seeds = self.make_spider(seed_mode='diff', refresh_days=7).gen_diff_seeds()
            now, stamp = seeding.read_seed_stamp(self.today)
            self.assertEqual(seeds, ['h1'])
            self.assertTrue(before <= now <= timezone.now())
            self.assertEqual(stamp['classes']['stale'], 1)
            self.assertEqual(stamp['seeds'], 1)
            self.assertTrue(seeding.seed_stamp_path(self.today).startswith(tmp))
        self.assertEqual(seeding.read_seed_stamp(self.today - timedelta(days=3000)), (None, None))

    def test_diff_mode_fresh_returned_not_reseeded(self):
        '''回列但 12 小時內 detail 過＝同輪已處理，不重排。'''
        now = timezone.now()
        self.make_house('fresh', detail_crawled_at=now - timedelta(hours=1))
        self.put_in_list('fresh', self.today)

        spider = self.make_spider(seed_mode='diff', refresh_days=7)
        self.assertEqual(spider.gen_diff_seeds(), [])

    def test_regen_guard_when_queue_drained_same_day(self):
        '''queue 恰好耗盡＋今天跑過 → 不重生成（2026-08-26：55,943 筆重排）。'''
        self.make_house('h1')
        spider = self.make_spider()

        with mock.patch.object(
                PersistQueue, 'has_run_today', return_value=True), \
             mock.patch.object(
                PersistQueue, 'init_progress_tracking', return_value=0):
            list(spider.start_detail_requests())

        self.assertEqual(RequestTS.objects.count(), 0)

    def test_seed_only_rerun_on_drained_day_does_not_regen(self):
        '''flow 續跑／orchestrate 同日重啟：queue 已排空＋今天跑過 →
        seed_only 不得全量重排（2026-08-26 同型陷阱的 seed_only 版）。'''
        self.make_house('h1')
        spider = self.make_spider(seed_only=True)

        with mock.patch.object(
                PersistQueue, 'has_run_today', return_value=True), \
             mock.patch.object(
                PersistQueue, 'init_progress_tracking', return_value=0):
            list(spider.start_detail_requests())

        self.assertEqual(RequestTS.objects.count(), 0)

    def test_seed_only_generates_without_crawling(self):
        self.make_house('h1')
        spider = self.make_spider(seed_only=True)

        with mock.patch.object(
                PersistQueue, 'has_run_today', return_value=False), \
             mock.patch.object(
                PersistQueue, 'init_progress_tracking', return_value=1):
            yielded = list(spider.start_detail_requests())

        self.assertEqual(yielded, [])
        self.assertEqual(RequestTS.objects.count(), 1)

    def test_consume_only_never_generates(self):
        self.make_house('h1')
        spider = self.make_spider(consume_only=True)

        with mock.patch.object(
                PersistQueue, 'init_progress_tracking', return_value=0):
            list(spider.start_detail_requests())

        self.assertEqual(RequestTS.objects.count(), 0)


class StateMachineTests(QueueTestMixin, TestCase):
    '''1-1 終結狀態機：errback 必寫終結狀態、attempts 上限轉 dead。'''

    def _claim(self, q, seed_id='h1'):
        q.gen_persist_request({'id': seed_id})
        return q.next_request()

    def _fail_via_errback(self, q, request, exception):
        '''觸發 errback 並回傳該列。名額先填滿：errback 會補餵（2026-09-05 修正），
        單列 queue 下會把剛 failed 的列立刻重新認領，要觀察 failed 中間態就不能
        留名額給它。回傳前把名額歸零，讓後續 next_request 照常。'''
        from twisted.python.failure import Failure
        failure = Failure(exception)
        failure.request = request
        q.n_live_spider = q.queue_length + 1
        replenished = q.handle_errback(failure)
        self.assertEqual(replenished, [])        # 名額滿 → 不補餵
        self.assertEqual(q.n_live_spider, q.queue_length)  # errback 釋放了一個名額
        q.n_live_spider = 0
        return request.meta['db_request']

    def test_http_errback_writes_failed_with_classification(self):
        from scrapy.spidermiddlewares.httperror import HttpError
        q = make_queue()
        request = self._claim(q)
        response = TextResponse(
            url=request.url, status=403, body=b'', request=request)

        row = self._fail_via_errback(q, request, HttpError(response))

        self.assert_retriable_failure(row.id, error='http_403')
        row.refresh_from_db()
        self.assertEqual(row.last_status, 403)

    def test_errback_replenishes_from_queue(self):
        '''收尾整批 errback 時不能斷餵：errback 要回傳補認領的 Request。'''
        queue = make_queue()
        for i in range(3):
            queue.gen_persist_request({'id': 'r{}'.format(i)})
        first = queue.next_request()
        queue.n_live_spider = queue.queue_length   # 模擬名額滿、其餘尚未認領
        failure = mock.Mock()
        failure.request = first
        failure.check.return_value = False
        failure.type = ValueError
        replenished = queue.handle_errback(failure)
        self.assertGreaterEqual(len(replenished), 1)
        self.assertTrue(all(isinstance(r, scrapy.Request) for r in replenished))
        self.assert_retriable_failure(first.meta['db_request'].id, 'ValueError')

    def test_network_errback_writes_type_name(self):
        from twisted.internet.error import TimeoutError as TxTimeoutError
        q = make_queue()
        request = self._claim(q)

        row = self._fail_via_errback(q, request, TxTimeoutError())

        self.assert_retriable_failure(row.id, error='TimeoutError')

    def test_errback_without_db_request_is_noop(self):
        from twisted.python.failure import Failure
        q = make_queue()
        failure = Failure(ValueError('no meta'))
        failure.request = scrapy.Request(url='https://example.com/robots.txt')
        q.handle_errback(failure)  # 不炸即可（robots 等非 queue 請求）

    def test_attempts_exhaustion_turns_dead(self):
        from twisted.internet.error import TimeoutError as TxTimeoutError
        q = make_queue()
        q.max_attempts = 2
        request = self._claim(q)

        # 第一次失敗：attempts=1 < 2 → failed，可再認領
        row = self._fail_via_errback(q, request, TxTimeoutError())
        self.assert_retriable_failure(row.id)
        # 重新認領（attempts=2）再失敗 → dead
        request2 = q.next_request()
        self.assertIsNotNone(request2)
        row = self._fail_via_errback(q, request2, TxTimeoutError())

        row.refresh_from_db()
        self.assertEqual(row.status, RequestStatus.DEAD)
        # dead 不再被認領
        self.assertIsNone(q.next_request())
        self.assertFalse(q.has_request())

    def test_release_claims_escalates_exhausted_to_dead(self):
        q = make_queue()
        q.max_attempts = 1
        self._claim(q)  # attempts=1 == max，收工釋放時直接 dead

        released = q.release_claims()

        self.assertEqual(released, 1)
        row = RequestTS.objects.get()
        self.assertEqual(row.status, RequestStatus.DEAD)
        self.assertIsNone(row.owner)

    def test_done_rows_survive_release_claims(self):
        q = make_queue(batch_size=1)
        q.gen_persist_request({'id': 'h1'})
        request = q.next_request()
        list(q.parser_wrapper(make_response(request.meta['db_request'])))

        self.assertEqual(q.release_claims(), 0)
        self.assert_completed(request.meta['db_request'].id)

    def test_remaining_work_excludes_terminal_rows(self):
        q = make_queue(batch_size=1)
        q.gen_persist_request({'id': 'h1'})
        q.gen_persist_request({'id': 'h2'})
        request = q.next_request()
        list(q.parser_wrapper(make_response(request.meta['db_request'])))

        self.assertEqual(q.get_total_count(), 1)  # DONE 不算剩餘工作


class QueueFinalizeTests(QueueTestMixin, TestCase):
    '''queuefinalize：seeds==terminals 斷言、零產出、dead 門檻、滾動清理。'''

    def setUp(self):
        super().setUp()
        self.vendor = Vendor.objects.get(name=VENDOR_NAME)

    def add_rows(self, request_type, status, n=1, error=None, attempts=1,
                 day=15):
        for _ in range(n):
            RequestTS.objects.create(
                year=2026, month=1, day=day, hour=0,
                request_type=request_type, vendor=self.vendor,
                seed={'id': 'x'}, status=status, error=error,
                attempts=attempts)

    def finalize(self, *args):
        from django.core.management import call_command
        call_command('queuefinalize', '--no-cleanup', *args)

    def assert_red(self, *fragments):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError) as ctx:
            self.finalize()
        for fragment in fragments:
            self.assertIn(fragment, str(ctx.exception))

    def test_green_when_all_terminal(self):
        self.add_rows(RequestType.LIST, RequestStatus.DONE, 3)
        self.add_rows(RequestType.DETAIL, RequestStatus.DONE, 100)
        self.finalize()  # 不炸即綠

    def test_red_on_residue(self):
        self.add_rows(RequestType.LIST, RequestStatus.DONE, 3)
        self.add_rows(RequestType.DETAIL, RequestStatus.DONE, 10)
        self.add_rows(RequestType.DETAIL, RequestStatus.FAILED, 2,
                      error='http_403')
        self.assert_red('未收斂', 'http_403')

    def test_red_on_dead_ratio_over_threshold(self):
        '''403 全滅場景：全數 dead——形式上 seeds==done+dead，但必須紅。'''
        self.add_rows(RequestType.LIST, RequestStatus.DONE, 3)
        self.add_rows(RequestType.DETAIL, RequestStatus.DEAD, 50,
                      error='http_403')
        self.assert_red('dead 比率', 'http_403')

    def test_green_with_dead_below_threshold(self):
        self.add_rows(RequestType.LIST, RequestStatus.DONE, 3)
        self.add_rows(RequestType.DETAIL, RequestStatus.DONE, 99)
        self.add_rows(RequestType.DETAIL, RequestStatus.DEAD, 1,
                      error='http_500')
        self.finalize()  # 1% < 5% 門檻：照列訊息、不當錯誤

    def test_red_on_zero_seeds(self):
        '''seed 零產出場景：detail 連一顆種子都沒有。'''
        self.add_rows(RequestType.LIST, RequestStatus.DONE, 3)
        self.assert_red('零種子')

    def test_cleanup_deletes_only_old_terminal_rows(self):
        from django.core.management import call_command
        # 舊 bucket、窗口外的列
        self.add_rows(RequestType.DETAIL, RequestStatus.DONE, 2, day=1)
        self.add_rows(RequestType.DETAIL, RequestStatus.FAILED, 1, day=1)
        RequestTS.objects.update(created=timezone.now() - timedelta(days=120))
        # 今日 bucket（窗口內、全終結 → 斷言綠）
        self.add_rows(RequestType.LIST, RequestStatus.DONE, 1)
        self.add_rows(RequestType.DETAIL, RequestStatus.DONE, 5)

        call_command('queuefinalize', '--cleanup-days', '90')

        # 窗口外 DONE 刪除；FAILED（未終結）即使過期也留著等對帳
        self.assertEqual(RequestTS.objects.count(), 7)
        self.assertEqual(
            RequestTS.objects.filter(
                status=RequestStatus.FAILED).count(), 1)


class QualityEngineTests(TestCase):
    '''1-2 斷言引擎：min/max、near、樣本門檻、疊窗即算、缺席降級。'''

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix='twrh-manifests-')
        self.assertions = os.path.join(self.dir, 'assertions.yaml')

    def write_spec(self, checks, defaults=None):
        import yaml
        with open(self.assertions, 'w') as f:
            yaml.safe_dump({
                'version': 1,
                'defaults': defaults or {
                    'window': 30, 'min_history': 3, 'min_samples': 100},
                'checks': checks,
            }, f, allow_unicode=True)

    def write_manifest(self, date_str, stage='detail', **payload):
        from crawlerrequest import manifests
        manifests.write_manifest({
            'schema': 1, 'stage': stage, 'date': date_str,
            'source': payload.pop('source', 'live'), **payload,
        }, base_dir=self.dir)

    def evaluate(self, date_str='2026-09-15'):
        from crawlerrequest import quality
        return quality.evaluate(
            date_str, assertions_path=self.assertions, base_dir=self.dir)

    def by_id(self, results, check_id):
        return next(r for r in results if r.check_id == check_id)

    def test_min_max_and_near(self):
        self.write_spec([
            {'id': 'c.min', 'stage': 'detail', 'metric': 'queue.seeds',
             'min': 1},
            {'id': 'c.max', 'stage': 'detail', 'metric': 'queue.residue',
             'max': 0},
            {'id': 'c.near', 'stage': 'detail', 'metric': 'dist.median_floor',
             'near': 4, 'tolerance': 1},
        ])
        self.write_manifest(
            '2026-09-15',
            queue={'seeds': 0, 'residue': 3}, dist={'median_floor': 6})

        results = self.evaluate()

        for check_id in ('c.min', 'c.max', 'c.near'):
            r = self.by_id(results, check_id)
            self.assertFalse(r.ok)
            self.assertFalse(r.advisory)

    def test_small_sample_skips_hard_assert(self):
        self.write_spec([
            {'id': 'c.dist', 'stage': 'detail', 'metric': 'dist.median_floor',
             'sample_n': 'dist.n', 'near': 4, 'tolerance': 1},
        ])
        self.write_manifest(
            '2026-09-15', dist={'n': 50, 'median_floor': 99})

        r = self.by_id(self.evaluate(), 'c.dist')
        self.assertTrue(r.ok)
        self.assertIn('跳過', r.message)

    def test_rolling_median_bootstrap_then_drift(self):
        self.write_spec([
            {'id': 'c.roll', 'stage': 'detail', 'metric': 'counts.n',
             'rolling_median_within': 0.2},
        ])
        # history 不足 → 暫緩（綠）
        self.write_manifest('2026-09-15', counts={'n': 100})
        r = self.by_id(self.evaluate(), 'c.roll')
        self.assertTrue(r.ok)
        self.assertIn('bootstrap', r.message)
        # 補齊 history：中位數 100，今日 50 → 相對差 50% > 20% → 紅
        for day in (11, 12, 13, 14):
            self.write_manifest('2026-09-{:02d}'.format(day),
                                counts={'n': 100})
        self.write_manifest('2026-09-15', counts={'n': 50})
        r = self.by_id(self.evaluate(), 'c.roll')
        self.assertFalse(r.ok)
        self.assertFalse(r.advisory)
        # 在容差內 → 綠
        self.write_manifest('2026-09-15', counts={'n': 90})
        self.assertTrue(self.by_id(self.evaluate(), 'c.roll').ok)

    def test_missing_metric_degrades_to_advisory(self):
        '''backfill manifest 缺 queue 節：不判紅、標 advisory（1-3 回補配套）。'''
        self.write_spec([
            {'id': 'c.q', 'stage': 'detail', 'metric': 'queue.seeds',
             'min': 1},
        ])
        self.write_manifest('2026-09-15', source='backfill', counts={'n': 5})

        r = self.by_id(self.evaluate(), 'c.q')
        self.assertFalse(r.ok)
        self.assertTrue(r.advisory)
        self.assertIn('backfill', r.message)

    def test_missing_manifest_is_hard_failure(self):
        self.write_spec([
            {'id': 'c.q', 'stage': 'detail', 'metric': 'queue.seeds',
             'min': 1},
        ])
        r = self.by_id(self.evaluate(), 'c.q')
        self.assertFalse(r.ok)
        self.assertFalse(r.advisory)
        self.assertIn('manifest 不存在', r.message)


class ConcurrentClaimTests(QueueTestMixin, TransactionTestCase):
    '''#21：FOR UPDATE SKIP LOCKED——並發認領不得撞列、不得漏列。'''

    N_ROWS = 40
    N_WORKERS = 4

    def test_parallel_claims_are_disjoint_and_complete(self):
        seeder = make_queue()
        for i in range(self.N_ROWS):
            seeder.gen_persist_request({'id': 'h{}'.format(i)})
        all_ids = set(RequestTS.objects.values_list('id', flat=True))

        claims = [[] for _ in range(self.N_WORKERS)]
        errors = []

        def worker(idx):
            try:
                q = make_queue()
                q.queue_length = self.N_ROWS  # 別讓 in-memory cap 擋認領
                while True:
                    request = q.next_request()
                    if request is None:
                        break
                    claims[idx].append(request.meta['db_request'].id)
            except Exception as err:  # pragma: no cover
                errors.append(err)
            finally:
                connection.close()

        threads = [
            threading.Thread(target=worker, args=(i,))
            for i in range(self.N_WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(errors, [])
        flat = [row_id for chunk in claims for row_id in chunk]
        self.assertEqual(len(flat), len(set(flat)), '同一列被認領兩次')
        self.assertEqual(set(flat), all_ids, '有列沒被任何 worker 認領')


class DealStageTests(QueueTestMixin, TestCase):
    '''deals stage（#229）：DEAL 類 queue 種子／續跑、未知物件過濾、
    syncstateful 照抄站方成交值、queuefinalize 對第三類型的處理。'''

    DEAL_BODY = (
        '<html><body><script>window.__NUXT__=(function(a,b,c){return {data:{x:{'
        'data:{dealDataList:['
        '{id:c,url:"https:\\u002F\\u002Frent.591.com.tw\\u002Fknown1",deal_total_day:"9天成交",deal_time:"今日"},'
        '{id:"ghost1",url:"https:\\u002F\\u002Frent.591.com.tw\\u002Fghost1",deal_total_day:"3天成交",deal_time:"昨日"},'
        '{id:"known2",url:"https:\\u002F\\u002Frent.591.com.tw\\u002Fknown2",deal_total_day:"5天成交",deal_time:"9天前"}'
        '],total:3}}}}}(0,"","known1"))</script></body></html>'
    )

    def setUp(self):
        super().setUp()
        self.vendor = Vendor.objects.get(name=VENDOR_NAME)
        from crawler.spiders.deal591_spider import Deal591Spider
        self.spider_cls = Deal591Spider
        from scrapy_twrh.spiders.rental591.util import DealRequestMeta
        self.meta_cls = DealRequestMeta

    def make_spider(self, **kwargs):
        kwargs.setdefault('target_cities', '台北市')
        return self.spider_cls(**kwargs)

    def deal_rows(self):
        return RequestTS.objects.filter(
            year=2026, month=1, day=15, hour=0, request_type=RequestType.DEAL)

    def test_seeds_page_one_per_city_with_pinned_base_date(self):
        spider = self.make_spider(lookback_days=3)
        requests = list(spider.start_deal_from_persist_queue())
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.deal_rows().count(), 1)
        self.assertEqual(self.deal_rows().get().seed, {'id': '1', 'name': '台北市', 'page': 1})
        self.assertEqual(spider.deal_lookback_days, 3)
        # 基準日＝queue 的日期（TWRH_TARGET_DATE），不是今天
        self.assertEqual(spider.deal_base_date.isoformat(), TEST_DATE)
        self.assertIn('shType=clinch', requests[0].url)
        self.assertIn('region=1&page=1', requests[0].url)

    def test_same_day_rerun_does_not_reseed_but_append_does(self):
        list(self.make_spider().start_deal_from_persist_queue())
        first = self.deal_rows().get()
        first.status = RequestStatus.DONE
        first.owner = None
        first.save()
        # 同日重跑：queue 已終結、不重生種子、沒有請求
        self.assertEqual(list(self.make_spider().start_deal_from_persist_queue()), [])
        self.assertEqual(self.deal_rows().count(), 1)
        # --append 強制重生
        self.assertEqual(len(list(self.make_spider(append='True').start_deal_from_persist_queue())), 1)
        self.assertEqual(self.deal_rows().count(), 2)

    def test_parse_writes_known_houses_only_and_persists_next_page(self):
        House.objects.create(vendor=self.vendor, vendor_house_id='known1')
        House.objects.create(vendor=self.vendor, vendor_house_id='known2')
        spider = self.make_spider(lookback_days=2)
        queue = spider.persist_queue
        queue.gen_persist_request({'id': '1', 'name': '台北市', 'page': 1})
        db_request = self.deal_rows().get()
        request = scrapy.Request(
            url='https://rent.591.com.tw/list?shType=clinch&region=1&page=1',
            meta={'rental': self.meta_cls('1', '台北市', 1), 'db_request': db_request})
        response = TextResponse(
            url=request.url, status=200, body=self.DEAL_BODY.encode('utf-8'),
            request=request, encoding='utf-8')

        out = list(spider.parse_deal_and_stop(response))
        events = [o for o in out if not isinstance(o, bool)]
        # known1 今日→事件；ghost1 未建檔→略過（計數）；known2 9 天前→窗外
        self.assertEqual([e['vendor_house_id'] for e in events], ['known1'])
        self.assertEqual(events[0]['deal_status'], enums.DealStatusType.DEAL)
        self.assertEqual(events[0]['deal_time'].date().isoformat(), TEST_DATE)
        self.assertEqual(events[0]['n_day_deal'], 9)
        self.assertEqual(spider.n_events, 1)
        self.assertEqual(spider.n_unknown, 1)
        self.assertIs(out[-1], True)
        # 本頁最舊已越過窗口（9 天前）→ 不再排下一頁
        self.assertEqual(self.deal_rows().count(), 1)

    def test_parse_persists_next_page_while_window_not_exhausted(self):
        spider = self.make_spider(lookback_days=30)
        spider.persist_queue.gen_persist_request({'id': '1', 'name': '台北市', 'page': 1})
        db_request = self.deal_rows().get()
        request = scrapy.Request(
            url='https://x/1', meta={'rental': self.meta_cls('1', '台北市', 1),
                                     'db_request': db_request})
        response = TextResponse(url=request.url, status=200,
                                body=self.DEAL_BODY.encode('utf-8'),
                                request=request, encoding='utf-8')
        list(spider.parse_deal_and_stop(response))
        seeds = sorted(r.seed['page'] for r in self.deal_rows())
        self.assertEqual(seeds, [1, 2])

    def test_syncstateful_keeps_vendor_provided_deal_values(self):
        from django.core.management import call_command
        deal_time = timezone.make_aware(timezone.datetime(2026, 1, 12))
        House.objects.create(vendor=self.vendor, vendor_house_id='h1',
                             deal_status=enums.DealStatusType.DEAL,
                             deal_time=deal_time, n_day_deal=17)
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='h1',
                               year=2026, month=1, day=15, hour=0,
                               deal_status=enums.DealStatusType.DEAL,
                               deal_time=deal_time, n_day_deal=17)
        # 對照組：舊路徑（detail 標 DEAL、無站方值）仍由 TS 序列推導
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='h2',
                               year=2026, month=1, day=15, hour=0,
                               deal_status=enums.DealStatusType.DEAL)
        House.objects.create(vendor=self.vendor, vendor_house_id='h2',
                             deal_status=enums.DealStatusType.DEAL)

        call_command('syncstateful', '-ts')

        h1 = House.objects.get(vendor_house_id='h1')
        self.assertEqual(h1.deal_time, deal_time)
        self.assertEqual(h1.n_day_deal, 17)
        h2 = House.objects.get(vendor_house_id='h2')
        self.assertEqual(h2.deal_status, enums.DealStatusType.DEAL)
        self.assertEqual(h2.n_day_deal, 1)
        self.assertIsNotNone(h2.deal_time)

    def test_queuefinalize_handles_deal_type_without_zero_seed_rule(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        def add(request_type, status, n=1):
            for _ in range(n):
                RequestTS.objects.create(
                    year=2026, month=1, day=15, hour=0, request_type=request_type,
                    vendor=self.vendor, seed={'id': 'x'}, status=status, attempts=1)

        add(RequestType.LIST, RequestStatus.DONE, 2)
        add(RequestType.DETAIL, RequestStatus.DONE, 50)
        # deals 沒種子的日子合法（stage 未排程）
        call_command('queuefinalize', '--no-cleanup')
        # 有列就要收斂：殘留一列 → 紅，且訊息點名 deal
        add(RequestType.DEAL, RequestStatus.DONE, 3)
        add(RequestType.DEAL, RequestStatus.FAILED, 1)
        with self.assertRaises(CommandError) as ctx:
            call_command('queuefinalize', '--no-cleanup')
        self.assertIn('deal', str(ctx.exception))
        self.assertNotIn('deal: 零種子', str(ctx.exception))

    def test_deals_manifest_counts_events_by_deal_date(self):
        from crawlerrequest.manifests import build_deals_manifest
        from datetime import date
        for hid, day, n in (('a', 15, 9), ('b', 14, 3), ('c', 14, 5)):
            HouseTS.objects.create(
                vendor=self.vendor, vendor_house_id=hid,
                year=2026, month=1, day=15, hour=0,
                deal_status=enums.DealStatusType.DEAL,
                deal_time=timezone.make_aware(timezone.datetime(2026, 1, day)),
                n_day_deal=n)
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='open',
                               year=2026, month=1, day=15, hour=0)
        manifest = build_deals_manifest(date(2026, 1, 15))
        self.assertEqual(manifest['stage'], 'deals')
        self.assertEqual(manifest['counts']['n_events'], 3)
        self.assertEqual(manifest['by_deal_date'], {'2026-01-14': 2, '2026-01-15': 1})
        self.assertEqual(manifest['dist']['median_n_day_deal'], 5)
        self.assertEqual(manifest['queue']['seeds'], 0)


class FrontierSweepTests(QueueTestMixin, TestCase):
    '''前緣掃描（短命物件）：list 前緣逐頁、整頁已知即收單；detail seed_mode=new。'''

    def setUp(self):
        super().setUp()
        self.vendor = Vendor.objects.get(name=VENDOR_NAME)
        from crawler.spiders.list591_spider import List591Spider
        from crawler.spiders.detail591_spider import Detail591Spider
        self.list_cls, self.detail_cls = List591Spider, Detail591Spider

    @staticmethod
    def list_body(ids):
        return ''.join(
            '<div class="item"><div class="item-info-title">'
            '<a href="https://rent.591.com.tw/{}">t</a></div></div>'.format(h)
            for h in ids)

    def frontier_parse(self, spider, page, ids):
        from scrapy_twrh.spiders.rental591.util import ListRequestMeta
        # parse_list_and_stop 不碰 db_request（那是 parser_wrapper 的事），直接餵 meta
        request = scrapy.Request(
            url='https://rent.591.com.tw/list?region=1&page={}'.format(page + 1),
            meta={'rental': ListRequestMeta('1', '台北市', page)})
        response = TextResponse(url=request.url, status=200,
                                body=self.list_body(ids).encode('utf-8'),
                                request=request, encoding='utf-8')
        out = list(spider.parse_list_and_stop(response))
        self.assertIs(out[-1], True)
        return [o for o in out if not isinstance(o, bool)]

    def list_rows(self):
        return RequestTS.objects.filter(
            year=2026, month=1, day=15, hour=0, request_type=RequestType.LIST)

    def test_frontier_seeds_every_city_even_when_day_has_records(self):
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='x',
                               year=2026, month=1, day=15, hour=0,
                               top_region=enums.TopRegionType['台北市'])
        spider = self.list_cls(target_cities='台北市', frontier_pages=5)
        requests = list(spider.start_list_from_persist_queue())
        self.assertEqual(len(requests), 1)   # 非 append 且當日已有紀錄，仍重生種子

    def test_frontier_pages_next_page_only_while_unseen(self):
        House.objects.create(vendor=self.vendor, vendor_house_id='k1')
        House.objects.create(vendor=self.vendor, vendor_house_id='k2')
        spider = self.list_cls(target_cities='台北市', frontier_pages=5)
        # 第 1 頁有沒見過的 → 排第 2 頁
        items = self.frontier_parse(spider, 0, ['n1', 'k1', 'n2'])
        self.assertEqual(len([i for i in items if isinstance(i, scrapy.Item)]) >= 3, True)
        self.assertEqual(sorted(r.seed['page'] for r in self.list_rows()), [1])
        self.assertEqual(spider.frontier_new, 2)
        # 第 2 頁整頁已知 → 收單，不排第 3 頁
        self.frontier_parse(spider, 1, ['k1', 'k2'])
        self.assertEqual(sorted(r.seed['page'] for r in self.list_rows()), [1])
        self.assertEqual(spider.frontier_new, 2)

    def test_frontier_page_cap_stops_even_with_unseen(self):
        spider = self.list_cls(target_cities='台北市', frontier_pages=2)
        self.frontier_parse(spider, 1, ['n1', 'n2'])   # 第 2 頁＝上限
        self.assertEqual(list(self.list_rows()), [])

    def test_frontier_empty_page_stops(self):
        spider = self.list_cls(target_cities='台北市', frontier_pages=5)
        with self.assertRaises(Exception):
            # 空頁沒有 .item／.paging／.empty → package 判版式不明、丟例外
            self.frontier_parse(spider, 0, [])

    def test_new_seed_mode_ignores_progress_guard_and_seeds_only_never_detailed(self):
        House.objects.create(vendor=self.vendor, vendor_house_id='new1')
        House.objects.create(vendor=self.vendor, vendor_house_id='new2')
        House.objects.create(vendor=self.vendor, vendor_house_id='old',
                             detail_crawled_at=timezone.now())
        House.objects.create(vendor=self.vendor, vendor_house_id='closed',
                             deal_status=enums.DealStatusType.NOT_FOUND)
        spider = self.detail_cls(seed_mode='new')
        self.assertEqual(sorted(spider.gen_new_seeds()), ['new1', 'new2'])
        with mock.patch.object(spider.persist_queue, 'has_run_today', return_value=True):
            requests = list(spider.start_detail_requests())
        self.assertEqual(len(requests), 2)
        # full 模式在同樣情境下會被 progress 防呆擋住（既有語意不變）
        spider_full = self.detail_cls()
        with mock.patch.object(spider_full.persist_queue, 'has_run_today', return_value=True):
            self.assertEqual(list(spider_full.start_detail_requests()), [])


class ListManifestCaptureTests(QueueTestMixin, TestCase):
    '''list manifest 的完整度哨兵：分母＝detail 確認開放（非合成）。'''

    def test_capture_uses_confirmed_open_and_reports_pending_absent(self):
        from crawlerrequest.manifests import build_list_manifest
        from datetime import date
        vendor = Vendor.objects.get(name=VENDOR_NAME)
        def row(hid, **kw):
            HouseTS.objects.create(vendor=vendor, vendor_house_id=hid,
                                   year=2026, month=1, day=15, hour=0, **kw)
        now = timezone.now()
        row('c1', list_crawled_at=now)                              # 確認開放、在 list
        row('c2', list_crawled_at=now)
        row('c3')                                                   # 確認開放、缺席（真漏抓）
        row('s1', is_synthesized=True, list_crawled_at=now)         # 合成、在 list（skip）
        row('s2', is_synthesized=True)                              # 合成、缺席（待確認關閉）
        row('s3', is_synthesized=True)
        row('x', deal_status=enums.DealStatusType.NOT_FOUND)
        m = build_list_manifest(date(2026, 1, 15))['capture']
        self.assertEqual((m['n_open'], m['n_open_in_list']), (6, 3))
        self.assertEqual((m['n_confirmed_open'], m['n_confirmed_open_in_list']), (3, 2))
        self.assertEqual(m['ratio'], 0.6667)
        self.assertEqual(m['ratio_all_open'], 0.5)
        self.assertEqual(m['n_pending_absent'], 2)


class RawPackTests(QueueTestMixin, TestCase):
    '''3-1 rawpack：同日多次 run 聯集（sweep 上線後）、孤兒日期、vendor 目錄
    正規化、對帳只報量（D5 後 DB 不存 raw）。'''

    def setUp(self):
        super().setUp()
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='twrh-rawpack-')
        self.env = mock.patch.dict(os.environ, {
            'TWRH_RAW_SCRATCH_DIR': os.path.join(self.tmp, 'scratch'),
            'TWRH_RAW_DIR': os.path.join(self.tmp, 'raws'),
            'TWRH_RAW_BUCKET': '',
        })
        self.env.start()
        self.vendor = Vendor.objects.get(name=VENDOR_NAME)

    def tearDown(self):
        import shutil
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def scratch(self, vendor_dir, date_str, house_id, html):
        day = os.path.join(self.tmp, 'scratch', vendor_dir, date_str)
        os.makedirs(day, exist_ok=True)
        with open(os.path.join(day, '{}.detail.html'.format(house_id)), 'w') as f:
            f.write(html)

    def members(self, date_str):
        import subprocess
        pack = os.path.join(self.tmp, 'raws', '591', date_str + '.tar.zst')
        out = subprocess.run(['tar', '-I', 'zstd', '-tf', pack],
                             capture_output=True, text=True, check=True)
        return sorted(out.stdout.split())

    def member(self, date_str, name):
        import subprocess
        pack = os.path.join(self.tmp, 'raws', '591', date_str + '.tar.zst')
        return subprocess.run(['tar', '-I', 'zstd', '-xOf', pack, name],
                              capture_output=True, check=True).stdout

    def rawpack(self, *args):
        from django.core.management import call_command
        call_command('rawpack', '--date', TEST_DATE, '--keep-local', *args)

    def test_same_day_runs_union_and_orphan_dates(self):
        # 日跑：A、B
        self.scratch('591', TEST_DATE, 'A', '<a1>')
        self.scratch('591', TEST_DATE, 'B', '<b1>')
        self.rawpack()
        self.assertEqual(self.members(TEST_DATE),
                         ['A.detail.html', 'B.detail.html'])
        # sweep：B 重爬（新內容）＋C；舊版全名目錄也要併；前一天孤兒 D
        self.scratch('591 租屋網', TEST_DATE, 'B', '<b2>')
        self.scratch('591 租屋網', TEST_DATE, 'C', '<c1>')
        self.scratch('591', '2026-01-14', 'D', '<d1>')
        self.rawpack()
        self.assertEqual(self.members(TEST_DATE),
                         ['A.detail.html', 'B.detail.html', 'C.detail.html'])
        self.assertEqual(self.member(TEST_DATE, 'B.detail.html'), b'<b2>')
        self.assertEqual(self.member(TEST_DATE, 'A.detail.html'), b'<a1>')
        self.assertEqual(self.members('2026-01-14'), ['D.detail.html'])
        # scratch 清空（含孤兒）
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp, 'scratch', '591', '2026-01-14')))
        with open(os.path.join(self.tmp, 'raws', '591',
                               TEST_DATE + '.index.jsonl')) as f:
            self.assertEqual(len(f.read().splitlines()), 3)

    def test_reconcile_reports_counts_only(self):
        '''D5 後 DB 無 raw：--reconcile／--reconcile-only 只報量，內容不比、恆綠。'''
        self.scratch('591', TEST_DATE, 'A', '<a1>')
        self.rawpack('--reconcile', '--full')
        self.rawpack('--reconcile-only', '--full')
        self.scratch('591', TEST_DATE, 'A', '<a-changed>')
        self.rawpack('--reconcile')
        self.assertEqual(self.member(TEST_DATE, 'A.detail.html'), b'<a-changed>')


class ContractTests(TestCase):
    '''4a／4b normalized 契約：指紋是雜湊、enum 落 int、座標拆 lat/lng、author 只留雜湊。'''

    def test_list_fingerprint_hash_only_price_title(self):
        from rental import contracts
        fp = contracts.list_fingerprint({'price': '15,000', 'title': 'A', 'update_time': '3小時內'})
        self.assertEqual(fp, contracts.list_fingerprint({'price': '15,000', 'title': 'A', 'update_time': '1天內'}))
        self.assertNotEqual(fp, contracts.list_fingerprint({'price': '16,000', 'title': 'A'}))
        self.assertEqual(len(fp), 16)
        self.assertNotIn('A', fp)

    def test_closure_item_is_detected(self):
        from rental import contracts
        closed = {'vendor': VENDOR_NAME, 'vendor_house_id': 'h', 'deal_status': 1}
        self.assertTrue(contracts.is_closure(closed))
        self.assertFalse(contracts.is_closure({**closed, 'deal_status': 0}))
        self.assertFalse(contracts.is_closure({**closed, 'monthly_price': 1}))   # 解析列
        self.assertFalse(contracts.is_deal_event(closed))

    def test_stub_and_parsed_rows_are_normalized(self):
        from rental import contracts
        now = timezone.now()
        stub = contracts.list_stub('591', 'h1', TEST_DATE, 'run', now, 'abcd', {
            'top_region': enums.TopRegionType.台北市, 'monthly_price': 15000,
            'property_type': enums.PropertyType.獨立套房, 'title': '不該落地'})
        self.assertEqual(stub['top_region'], int(enums.TopRegionType.台北市))
        self.assertNotIn('title', stub)
        self.assertEqual(stub['stub_version'], contracts.LIST_STUB_VERSION)
        row = contracts.parsed_row('591', 'h1', TEST_DATE, 'run', now, '2.4.0', {
            'rough_coordinate': (25.03, 121.56), 'author': '0912345678',
            'contact': enums.ContactType.屋主, 'imgs': ['a', 'b'],
            'deal_status': enums.DealStatusType.OPENED})
        self.assertEqual((row['rough_lat'], row['rough_lng']), (25.03, 121.56))
        self.assertNotIn('author', row)
        self.assertEqual(len(row['author_key']), 16)
        coerced = contracts.coerce_row(row, contracts.PARSED_FIELDS)
        self.assertEqual(coerced['imgs'], '["a", "b"]')
        self.assertEqual(coerced['crawled_at'], now)
        self.assertEqual(set(coerced), {name for name, _ in contracts.PARSED_FIELDS})
        contracts.arrow_schema(contracts.PARSED_FIELDS)   # pyarrow 可建

    def test_contract_field_names_match_house_columns(self):
        '''契約欄位（來源欄與拆解欄除外）都必須是 BaseHouse 現有欄——防止漂移。'''
        from rental import contracts
        columns = {f.name for f in House._meta.get_fields()}
        extra = {'date', 'run', 'crawled_at', 'parser_version', 'rough_lat',
                 'rough_lng', 'author_key', 'parsed_version', 'seen_at',
                 'fingerprint', 'stub_version'}
        for name, _ in contracts.PARSED_FIELDS + contracts.LIST_STUB_FIELDS:
            if name not in extra:
                self.assertIn(name, columns, name)


class ArtifactPackTests(TestCase):
    '''4a／4b artifactpack：shard → 一輪一檔；parsed 去重後爬者勝；同 run 重打聯集；
    不同 run 各自成檔、不互相改寫；孤兒日期也打。'''

    def setUp(self):
        super().setUp()
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='twrh-artifacts-')
        self.env = mock.patch.dict(os.environ, {
            'TWRH_ARTIFACT_DIR': self.tmp, 'TWRH_RAW_BUCKET': ''})
        self.env.start()

    def tearDown(self):
        import shutil
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def write_rows(self, tree, run, rows, date_str=TEST_DATE):
        from rental import artifacts
        with mock.patch.dict(os.environ, {'TWRH_RUN_ID': run}):
            writer = artifacts.ShardWriter(tree)
            for row in rows:
                writer.append({'vendor': '591', 'date': date_str, 'run': run, **row})
            writer.close()

    def pack(self, tree):
        from django.core.management import call_command
        call_command('artifactpack', '--tree', tree, '--date', TEST_DATE, '--no-upload')

    def test_list_stubs_one_file_per_run_and_union_on_rerun(self):
        from rental import artifacts
        t = timezone.now().isoformat()
        self.write_rows('list', 'run', [
            {'vendor_house_id': 'a', 'seen_at': t, 'fingerprint': 'f1', 'monthly_price': 1},
            {'vendor_house_id': 'b', 'seen_at': t, 'fingerprint': 'f2'}])
        self.pack('list')
        self.write_rows('list', 'sweep-0500', [
            {'vendor_house_id': 'c', 'seen_at': t, 'fingerprint': 'f3'}])
        self.write_rows('list', 'run', [   # 同 run 重跑（--from list）：聯集
            {'vendor_house_id': 'd', 'seen_at': t, 'fingerprint': 'f4'}])
        self.pack('list')
        files = artifacts.list_partition_files('591', TEST_DATE)
        self.assertEqual([os.path.basename(p) for p in files],
                         ['run.jsonl.zst', 'sweep-0500.jsonl.zst'])
        rows = list(artifacts.read_list_stubs('591', TEST_DATE))
        self.assertEqual(sorted(r['vendor_house_id'] for r in rows), ['a', 'b', 'c', 'd'])
        self.assertEqual(next(r for r in rows if r['vendor_house_id'] == 'a')['monthly_price'], 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'scratch', 'list', '591', TEST_DATE)))

    def test_local_partitions_lists_packed_runs(self):
        from rental import artifacts
        t = timezone.now().isoformat()
        self.write_rows('list', 'run', [{'vendor_house_id': 'a', 'seen_at': t, 'fingerprint': 'f'}])
        self.write_rows('list', 'sweep-0800', [{'vendor_house_id': 'b', 'seen_at': t, 'fingerprint': 'f'}])
        self.pack('list')
        self.assertEqual([(v, r) for v, r, _ in artifacts.local_partitions('list', TEST_DATE)],
                         [('591', 'run'), ('591', 'sweep-0800')])
        self.assertEqual(artifacts.local_partitions('parsed', TEST_DATE), [])

    def test_parsed_parquet_dedups_latest_and_packs_orphans(self):
        import pyarrow.parquet as pq
        from rental import artifacts
        early = (timezone.now() - timedelta(hours=1)).isoformat()
        late = timezone.now().isoformat()
        self.write_rows('parsed', 'run', [
            {'vendor_house_id': 'a', 'crawled_at': late, 'monthly_price': 20000,
             'imgs': ['x'], 'top_region': 17},
            {'vendor_house_id': 'a', 'crawled_at': early, 'monthly_price': 10000},
            {'vendor_house_id': 'b', 'crawled_at': late}])
        self.write_rows('parsed', 'sweep-2300', [
            {'vendor_house_id': 'z', 'crawled_at': late}], date_str='2026-01-14')
        self.pack('parsed')
        table = pq.read_table(artifacts.partition_path('parsed', '591', TEST_DATE, 'run'))
        self.assertEqual(table.num_rows, 2)
        a = table.to_pylist()[0]
        self.assertEqual((a['vendor_house_id'], a['monthly_price'], a['imgs']),
                         ('a', 20000, '["x"]'))
        self.assertEqual(table.schema.field('crawled_at').type.tz, 'UTC')
        orphan = artifacts.partition_path('parsed', '591', '2026-01-14', 'sweep-2300')
        self.assertTrue(os.path.exists(orphan))


class ParsedCheckTests(QueueTestMixin, TestCase):
    '''4b 對帳：parquet 對 HouseTS 逐欄；Point 依專案約定 x=lat／y=lng；
    parquet NULL 而 DB 有值（list 才有的欄）不算錯；狀態欄變動只計數。'''

    def setUp(self):
        super().setUp()
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='twrh-parsedcheck-')
        self.env = mock.patch.dict(os.environ, {'TWRH_ARTIFACT_DIR': self.tmp, 'TWRH_RAW_BUCKET': ''})
        self.env.start()
        self.vendor = Vendor.objects.get(name=VENDOR_NAME)

    def tearDown(self):
        import shutil
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_agree_and_diff(self):
        from io import StringIO
        from django.contrib.gis.geos import Point
        from django.core.management import call_command
        from rental import artifacts, contracts
        from rental.models import Author
        y, m, d = (int(x) for x in TEST_DATE.split('-'))
        now = timezone.now()
        author = Author.objects.create(truth='0912')
        HouseTS.objects.create(
            vendor=self.vendor, vendor_house_id='h', year=y, month=m, day=d, hour=0,
            monthly_price=15000, rough_coordinate=Point(25.03, 121.56, srid=4326),
            imgs=['a'], author=author, deal_status=enums.DealStatusType.DEAL, crawled_at=now)
        House.objects.create(vendor=self.vendor, vendor_house_id='h', detail_crawled_at=now)
        row = contracts.parsed_row('591', 'h', TEST_DATE, 'run', now, 'x', {
            'monthly_price': 15000, 'rough_coordinate': (25.03, 121.56), 'author': '0912',
            'deal_status': enums.DealStatusType.OPENED})
        with mock.patch.dict(os.environ, {'TWRH_RUN_ID': 'run'}):
            w = artifacts.ShardWriter('parsed'); w.append(row); w.close()
        call_command('artifactpack', '--tree', 'parsed', '--date', TEST_DATE, '--no-upload')
        out = StringIO()
        with mock.patch('sys.stdout', out):
            call_command('parsedcheck', '--date', TEST_DATE)
        text = out.getvalue()
        self.assertIn('parsedcheck: AGREE', text)
        self.assertIn('"parquet_null_db_set": {"imgs": 1}', text)
        self.assertIn('"deal_status": 1', text)
        # 價格改了 → DIFF
        HouseTS.objects.filter(vendor_house_id='h').update(monthly_price=16000)
        out = StringIO()
        with mock.patch('sys.stdout', out):
            call_command('parsedcheck', '--date', TEST_DATE)
        self.assertIn('parsedcheck: DIFF', out.getvalue())
        self.assertIn('"monthly_price": 1', out.getvalue())


class PipelineClosureRowTests(QueueTestMixin, TestCase):
    '''detail 404 的 GenericHouseItem（只帶 deal_status=NOT_FOUND）也要落 parsed 列，
    snapshot fold 才摺得出 NOT_FOUND（DEAL sticky 由 fold 處理）。'''

    def setUp(self):
        super().setUp()
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='twrh-closure-')
        self.env = mock.patch.dict(os.environ, {'TWRH_ARTIFACT_DIR': self.tmp, 'TWRH_RAW_BUCKET': '',
                                                'TWRH_RUN_ID': 'run', 'TWRH_RAW_SINK': '0'})
        self.env.start()

    def tearDown(self):
        import shutil
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_not_found_item_writes_parsed_row_and_folds_closed(self):
        from django.core.management import call_command
        from crawler.pipelines import CrawlerPipeline
        from rental import artifacts, snapshot
        from scrapy_twrh.items import GenericHouseItem
        y, m, d = (int(x) for x in TEST_DATE.split('-'))
        pipeline = CrawlerPipeline()
        pipeline.process_item(GenericHouseItem(
            vendor=VENDOR_NAME, vendor_house_id='gone', deal_status=enums.DealStatusType.NOT_FOUND), None)
        pipeline.close_spider()
        call_command('artifactpack', '--tree', 'parsed', '--date', TEST_DATE, '--no-upload')
        rows = artifacts.read_parsed_rows('591', TEST_DATE)
        self.assertEqual([(r['vendor_house_id'], r['deal_status'], r['monthly_price']) for r in rows],
                         [('gone', int(enums.DealStatusType.NOT_FOUND), None)])
        self.assertEqual(House.objects.get(vendor_house_id='gone').deal_status,
                         enums.DealStatusType.NOT_FOUND)
        prev = snapshot._blank('591', 'gone', '2026-01-14')
        prev.update({'monthly_price': 9000, 'rough_lat': 25.0, 'source': 'detail',
                     'last_detail_at': timezone.now()})
        today = {r['vendor_house_id']: r for r in snapshot.fold([prev], [], rows, [], TEST_DATE)}
        # 404 只改狀態：租金／座標保留最後已知值、source 不變成 detail
        self.assertEqual((today['gone']['deal_status'], today['gone']['source'],
                          today['gone']['monthly_price'], today['gone']['rough_lat']),
                         (snapshot.NOT_FOUND, 'carry', 9000, 25.0))
        # DEAL sticky：昨日 DEAL 的戶 404 仍是 DEAL
        prev['deal_status'] = snapshot.DEAL
        today = {r['vendor_house_id']: r for r in snapshot.fold([prev], [], rows, [], TEST_DATE)}
        self.assertEqual(today['gone']['deal_status'], snapshot.DEAL)

    def test_synthts_fills_closed_and_dealt_rows_from_house(self):
        from django.core.management import call_command
        y, m, d = (int(x) for x in TEST_DATE.split('-'))
        vendor = Vendor.objects.get(name=VENDOR_NAME)
        old = timezone.now() - timedelta(days=3)
        House.objects.create(vendor=vendor, vendor_house_id='c', monthly_price=12000, floor_ping=10.0,
                             deal_status=enums.DealStatusType.NOT_FOUND, detail_crawled_at=old)
        HouseTS.objects.create(vendor=vendor, vendor_house_id='c', year=y, month=m, day=d, hour=0,
                               deal_status=enums.DealStatusType.NOT_FOUND)
        House.objects.create(vendor=vendor, vendor_house_id='k', monthly_price=8000,
                             deal_status=enums.DealStatusType.DEAL, deal_time=timezone.now(), n_day_deal=2,
                             detail_crawled_at=old)
        HouseTS.objects.create(vendor=vendor, vendor_house_id='k', year=y, month=m, day=d, hour=0,
                               deal_status=enums.DealStatusType.DEAL, deal_time=timezone.now(), n_day_deal=2)
        # Issue #9：House 已回滾成 DEAL、當日列是 NOT_FOUND → 狀態三欄不動
        House.objects.create(vendor=vendor, vendor_house_id='s', monthly_price=5000,
                             deal_status=enums.DealStatusType.DEAL, deal_time=timezone.now(), n_day_deal=1)
        HouseTS.objects.create(vendor=vendor, vendor_house_id='s', year=y, month=m, day=d, hour=0,
                               deal_status=enums.DealStatusType.NOT_FOUND)
        # 早已關閉、今天沒列的戶：不建列
        House.objects.create(vendor=vendor, vendor_house_id='z', monthly_price=1,
                             deal_status=enums.DealStatusType.NOT_FOUND)
        # 回補過去日期用 --closed-only：不建 OPENED 戶的列
        House.objects.create(vendor=vendor, vendor_house_id='o', monthly_price=3,
                             deal_status=enums.DealStatusType.OPENED)
        call_command('synthts', '--closed-only')
        self.assertFalse(HouseTS.objects.filter(vendor_house_id='o').exists())
        self.assertEqual(HouseTS.objects.get(vendor_house_id='c').monthly_price, 12000)
        call_command('synthts')
        self.assertTrue(HouseTS.objects.filter(vendor_house_id='o').exists())
        c = HouseTS.objects.get(vendor_house_id='c')
        k = HouseTS.objects.get(vendor_house_id='k')
        s_row = HouseTS.objects.get(vendor_house_id='s')
        self.assertEqual((c.monthly_price, c.floor_ping, c.is_synthesized, c.deal_status),
                         (12000, 10.0, True, enums.DealStatusType.NOT_FOUND))
        self.assertEqual((k.monthly_price, k.is_synthesized, k.deal_status), (8000, True, enums.DealStatusType.DEAL))
        self.assertEqual((s_row.monthly_price, s_row.deal_status, s_row.deal_time),
                         (5000, enums.DealStatusType.NOT_FOUND, None))
        self.assertFalse(HouseTS.objects.filter(vendor_house_id='z').exists())


class FileQueueTests(TestCase):
    '''4e 檔案 queue（純檔案、無 DB）：摺疊語意、attempts 跨檔累計、殘留／孤兒、位置輪分。'''

    def setUp(self):
        super().setUp()
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='twrh-filequeue-')
        self.env = mock.patch.dict(os.environ, {'TWRH_ARTIFACT_DIR': self.tmp})
        self.env.start()

    def tearDown(self):
        import shutil
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_reconcile_folds_terminals_across_runs_and_workers(self):
        from rental import filequeue as fq
        seeds = fq.SeedsWriter('591', TEST_DATE, 'detail', 'run')
        for k in ('1', '2', '3', '4', '5'):
            seeds.append(k, {'id': 'h' + k})
        seeds.close()
        w1 = fq.TerminalWriter('591', TEST_DATE, 'detail', 'run', 'worker-a')
        w2 = fq.TerminalWriter('591', TEST_DATE, 'detail', 'sweep-0800', 'worker-b')
        w1.append('1', 'done', 1, http=200)
        w1.append('2', 'failed', 1, error='http_403')        # 之後別的 run 做完
        w2.append('2', 'done', 2, http=200)
        w1.append('3', 'failed', 1, error='http_403')
        w2.append('3', 'failed', 3, error='http_403')        # attempts 達上限 → dead
        w1.append('4', 'failed', 1, error='TimeoutError')    # 仍可重試 → residue
        w2.append('9', 'done', 1)                             # 沒種子 → orphan
        w1.close(); w2.close()

        r = fq.reconcile('591', TEST_DATE, 'detail', max_attempts=3)
        self.assertEqual((r['seeds'], r['done'], r['dead'], r['residue']), (5, 2, 1, 2))
        self.assertEqual(r['retriable_failed'], 1)
        self.assertEqual(r['orphan_terminals'], 1)
        self.assertEqual(r['errors'], {'http_403': 1, 'TimeoutError': 1})
        rem = fq.remaining('591', TEST_DATE, 'detail', max_attempts=3)
        self.assertEqual({k: a for k, (_s, a) in rem.items()}, {'4': 1, '5': 0})
        self.assertEqual(fq.type_names('591', TEST_DATE), ['detail'])

    def test_shard_is_positional_and_exact(self):
        from rental.filequeue import shard
        keys = [str(i) for i in range(10)]
        parts = [shard(keys, i, 3) for i in range(3)]
        self.assertEqual([len(p) for p in parts], [4, 3, 3])
        self.assertEqual(sorted(sum(parts, [])), sorted(keys))
        self.assertEqual(shard(['b', 'a', 'c'], 0, 2), ['a', 'c'])
        with self.assertRaises(ValueError):
            shard(keys, 3, 3)


class FileQueueDualWriteTests(QueueTestMixin, TestCase):
    '''4e 雙軌：PersistQueue 的種子／done／failed／dead／release 都同步落檔，
    reconcile 與 DB 計數一致（filequeuecheck AGREE）。'''

    def setUp(self):
        super().setUp()
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='twrh-fqdual-')
        self.env = mock.patch.dict(os.environ, {'TWRH_ARTIFACT_DIR': self.tmp, 'TWRH_RUN_ID': 'run'})
        self.env.start()

    def tearDown(self):
        import shutil
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_dual_write_matches_db(self):
        from io import StringIO
        from django.core.management import call_command
        from rental import filequeue as fq

        def exploding(_response):
            raise ValueError('boom')
        # batch_size=1：wrapper 收工後不補貨，認領順序由測試掌控
        q = make_queue(batch_size=1, parse_response=lambda r: iter([True]))
        q.max_attempts = 1
        for k in ('a', 'b', 'c', 'd'):
            q.gen_persist_request({'id': k})
        # a：done
        r1 = q.next_request(); list(q.parser_wrapper(make_response(r1.meta['db_request'])))
        # b：parse error，attempts 1 >= max 1 → dead
        q.parse_response = exploding
        r2 = q.next_request(); list(q.parser_wrapper(make_response(r2.meta['db_request'])))
        # c：認領後不處理 → release 時 dead（attempts 已達上限）
        q.next_request()
        q.release_claims()
        # d：從未認領 → residue
        r = fq.reconcile('591', TEST_DATE, 'detail', max_attempts=1)
        self.assertEqual((r['seeds'], r['done'], r['dead'], r['residue']), (4, 1, 2, 1))
        self.assertEqual(r['orphan_terminals'], 0)
        out = StringIO()
        with mock.patch('sys.stdout', out):
            call_command('filequeuecheck', '--date', TEST_DATE)
        self.assertIn('filequeuecheck: AGREE', out.getvalue())
        self.assertIn('file seeds 4 = done 1 + dead 2 + residue 1', out.getvalue())


class SnapshotFoldTests(TestCase):
    '''4c snapshot 摺疊純函數：detail／list／carry 三種來源、carry 欄遞推、
    DEAL sticky、deals 事件優先、已關閉且無訊號不攜帶。無 DB。'''

    D1, D2 = '2026-01-15', '2026-01-16'

    def stub(self, hid, at, fp='f1', price=10000):
        return {'vendor_house_id': hid, 'seen_at': at, 'fingerprint': fp, 'monthly_price': price}

    def parsed(self, hid, at, status=0, price=10000):
        return {'vendor_house_id': hid, 'crawled_at': at, 'deal_status': status,
                'monthly_price': price, 'floor_ping': 12.5}

    def test_day_one_and_day_two_carry_semantics(self):
        from rental.snapshot import fold
        day1 = fold([], [self.stub('a', 'T1'), self.stub('b', 'T1'), self.stub('c', 'T1')],
                    [self.parsed('a', 'T1d'), self.parsed('b', 'T1d')], [], self.D1)
        by = {r['vendor_house_id']: r for r in day1}
        self.assertEqual({k: v['source'] for k, v in by.items()}, {'a': 'detail', 'b': 'detail', 'c': 'list'})
        self.assertEqual((by['a']['last_detail_at'], by['a']['fingerprint_at_last_detail'],
                          by['a']['first_seen_at'], by['a']['days_absent']), ('T1d', 'f1', 'T1', 0))
        self.assertEqual(by['c']['floor_ping'], None)
        self.assertEqual(set(by['a']), {name for name, _ in __import__('rental.contracts', fromlist=['x']).SNAPSHOT_FIELDS})

        # day 2：a 只在 list 且價格變、b 缺席、c 有 detail、d 新戶
        day2 = fold(day1, [self.stub('a', 'T2', fp='f2', price=12000), self.stub('d', 'T2')],
                    [self.parsed('c', 'T2d')], [], self.D2)
        by = {r['vendor_house_id']: r for r in day2}
        self.assertEqual(by['a']['source'], 'list')
        self.assertEqual((by['a']['monthly_price'], by['a']['floor_ping']), (12000, 12.5))   # list 覆蓋、detail 欄沿用
        self.assertEqual((by['a']['last_detail_at'], by['a']['fingerprint_at_last_detail']), ('T1d', 'f1'))
        self.assertEqual((by['a']['last_seen_at'], by['a']['first_seen_at']), ('T2', 'T1'))
        self.assertEqual((by['b']['source'], by['b']['days_absent'], by['b']['last_seen_at']), ('carry', 1, 'T1'))
        self.assertEqual((by['c']['source'], by['c']['last_detail_at'], by['c']['fingerprint_at_last_detail']),
                         ('detail', 'T2d', 'f1'))                       # 今日沒在 list：用最後已知指紋
        self.assertEqual((by['a']['last_fingerprint'], by['c']['last_fingerprint']), ('f2', 'f1'))
        self.assertEqual((by['d']['source'], by['d']['first_seen_at'], by['d']['date']), ('list', 'T2', self.D2))

    def test_deal_sticky_and_vendor_event_wins(self):
        from rental.snapshot import fold, DEAL, NOT_FOUND
        day1 = fold([], [self.stub('x', 'T1'), self.stub('y', 'T1'), self.stub('z', 'T1')],
                    [self.parsed('x', 'T1d')], [], self.D1)
        # x：deals 事件；y：detail 404 → NOT_FOUND；z：無訊號 → carry
        day2 = fold(day1, [], [self.parsed('y', 'T2d', status=NOT_FOUND)],
                    [{'vendor_house_id': 'x', 'seen_at': 'T2', 'deal_time': 'D', 'n_day_deal': 3}], self.D2)
        by = {r['vendor_house_id']: r for r in day2}
        self.assertEqual((by['x']['deal_status'], by['x']['deal_time'], by['x']['n_day_deal'], by['x']['deal_source']),
                         (DEAL, 'D', 3, 'deals'))
        self.assertEqual((by['y']['deal_status'], by['y']['deal_source']), (NOT_FOUND, None))
        self.assertEqual((by['z']['source'], by['z']['days_absent']), ('carry', 1))
        # day 3：x 的 detail 回 NOT_FOUND → sticky 留 DEAL；y／x 已關閉且無訊號 → 不攜帶
        day3 = fold(day2, [], [self.parsed('x', 'T3d', status=NOT_FOUND)], [], '2026-01-17')
        by = {r['vendor_house_id']: r for r in day3}
        self.assertEqual(sorted(by), ['x', 'z'])
        self.assertEqual((by['x']['deal_status'], by['x']['deal_source'], by['x']['n_day_deal']), (DEAL, 'deals', 3))
        self.assertEqual(by['z']['days_absent'], 2)


class SeedFunctionTests(TestCase):
    '''4a seed 純函數：四類（stale／指紋／缺席／回列）＋skip，與 SeedMatrixTests 的
    DB 版同一組案例；無 DB、無 Django model。'''

    def stub(self, hid, fp='same', at=None):
        return {'vendor_house_id': hid, 'fingerprint': fp,
                'seen_at': (at or timezone.now()).isoformat()}

    def test_four_seed_classes_and_skip(self):
        from rental.seeding import HouseState, select_seeds
        now = timezone.now()
        d = timedelta
        state = {
            'stale': HouseState(open=True, detail_crawled_at=now - d(days=8)),
            'new': HouseState(open=True),
            'fp_legacy': HouseState(open=True, detail_crawled_at=now - d(days=2),
                                    fingerprint_changed_at=now - d(days=1)),
            'fp_carry': HouseState(open=True, detail_crawled_at=now - d(days=2),
                                   fingerprint_at_last_detail='old'),
            'absent': HouseState(open=True, detail_crawled_at=now - d(days=2)),
            'returned': HouseState(open=True, detail_crawled_at=now - d(days=2)),
            'skip': HouseState(open=True, detail_crawled_at=now - d(days=2),
                               fingerprint_at_last_detail='same'),
            'ctrl_yesterday': HouseState(open=True, detail_crawled_at=now - d(days=2)),
            'fresh_returned': HouseState(open=True, detail_crawled_at=now - d(hours=1)),
            'dealt': HouseState(open=False),
        }
        today = [self.stub('stale'), self.stub('new'), self.stub('fp_legacy'),
                 self.stub('fp_carry', fp='new'), self.stub('returned'),
                 self.stub('skip'), self.stub('ctrl_yesterday'),
                 self.stub('fresh_returned'), self.stub('dealt')]
        yesterday = {'skip', 'ctrl_yesterday'}

        r = select_seeds(today, yesterday, state, now, refresh_days=7)

        self.assertEqual(r.stale, {'stale', 'new'})
        self.assertEqual(r.fingerprint, {'fp_legacy', 'fp_carry'})
        self.assertEqual(r.absent, {'absent'})
        self.assertEqual(r.returned, {'stale', 'new', 'fp_legacy', 'fp_carry', 'returned'})
        self.assertEqual(sorted(r.seeds),
                         ['absent', 'fp_carry', 'fp_legacy', 'new', 'returned', 'stale'])
        self.assertEqual(r.n_open, 9)
        self.assertEqual(r.n_in_list, 9)          # dealt 也在 list（stub 不看狀態）
        self.assertEqual(r.skipped, 8 - 5)        # open∩today 8 − seeds∩today 5

    def test_latest_fingerprint_wins_across_runs(self):
        from rental.seeding import HouseState, select_seeds, latest_fingerprints
        now = timezone.now()
        today = [self.stub('h', fp='old', at=now - timedelta(hours=5)),
                 self.stub('h', fp='new', at=now - timedelta(hours=1))]
        self.assertEqual(latest_fingerprints(today), {'h': 'new'})
        state = {'h': HouseState(open=True, detail_crawled_at=now - timedelta(days=1),
                                 fingerprint_at_last_detail='old')}
        self.assertEqual(select_seeds(today, {'h'}, state, now).fingerprint, {'h'})

    def test_new_mode_seeds_only_never_detailed(self):
        from rental.seeding import HouseState, select_new_seeds
        state = {'a': HouseState(open=True), 'b': HouseState(open=True, detail_crawled_at=timezone.now()),
                 'c': HouseState(open=False)}
        self.assertEqual(select_new_seeds([self.stub('a'), self.stub('b'), self.stub('c'), self.stub('x')], state), {'a'})


class VendorProfileTests(TestCase):
    '''D6b：vendor profile 是資料、env 可覆寫；flow 依它組 stage。'''

    def test_profile_values_and_env_override(self):
        from crawler import vendor_profiles
        p = vendor_profiles.get('591')
        self.assertEqual(p.name, VENDOR_NAME)
        self.assertEqual(p.list_spider, 'list591')
        self.assertTrue(p.has_deals_stage)
        self.assertTrue(p.supports_frontier)
        self.assertEqual(p.frontier_pages, '30')
        with mock.patch.dict(os.environ, {'TWRH_SWEEP_PAGES': '12',
                                          'TWRH_DEAL_LOOKBACK_DAYS': '9'}):
            self.assertEqual(p.frontier_pages, '12')
            self.assertEqual(p.deal_lookback_days, '9')
        with self.assertRaises(KeyError):
            vendor_profiles.get('nope')
        with self.assertRaises(AttributeError):
            p.no_such_key


class QueueBusyTests(QueueTestMixin, TestCase):
    '''D6b：flow sweep 的互斥——同 vendor 同日 bucket、近期更新的 in_flight 才算忙。'''

    def busy(self, **kw):
        from django.core.management import call_command
        try:
            call_command('queuebusy', '--vendor', VENDOR_NAME, **kw)
        except SystemExit as e:
            return e.code
        return 0

    def test_idle_when_no_in_flight(self):
        q = make_queue(); q.gen_persist_request({'id': 'a'})
        self.assertEqual(self.busy(), 0)

    def test_busy_when_recent_in_flight_same_vendor_only(self):
        q = make_queue(); q.gen_persist_request({'id': 'a'})
        RequestTS.objects.update(status=RequestStatus.IN_FLIGHT)
        self.assertEqual(self.busy(), 1)
        # 其他 vendor 的 in_flight 不擋
        other = Vendor.objects.exclude(name=VENDOR_NAME).first()
        RequestTS.objects.update(vendor=other)
        self.assertEqual(self.busy(), 0)

    def test_stale_in_flight_does_not_block(self):
        q = make_queue(); q.gen_persist_request({'id': 'a'})
        RequestTS.objects.update(
            status=RequestStatus.IN_FLIGHT,
            updated=timezone.now() - timedelta(hours=3))
        self.assertEqual(self.busy(), 0)
        self.assertEqual(self.busy(hours=4), 1)


class ManifestChecksTests(TestCase):
    '''advisory 對帳判定落 manifests/<date>/checks.json（flow advisory_check →
    qualitycheck Slack 摘要）：同 run 同 name 後寫者勝、不同 run 並存、缺檔回空殼。'''

    def test_record_and_load(self):
        import tempfile
        from crawlerrequest import manifest_files as mf
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(mf.load_checks('2026-09-11', base)['runs'], {})
            mf.record_check('2026-09-11', 'run', 'seedcheck', 'crashed(exit -9)', '', base)
            mf.record_check('2026-09-11', 'run', 'seedcheck', 'AGREE', 'seedcheck: AGREE — {}', base)
            mf.record_check('2026-09-11', 'sweep-0502', 'filequeuecheck', 'DIFF', 'filequeuecheck: DIFF', base)
            runs = mf.load_checks('2026-09-11', base)['runs']
            self.assertEqual(runs['run']['seedcheck']['verdict'], 'AGREE')
            self.assertEqual(runs['run']['seedcheck']['line'], 'seedcheck: AGREE — {}')
            self.assertEqual(runs['sweep-0502']['filequeuecheck']['verdict'], 'DIFF')
            self.assertTrue(os.path.exists(mf.manifest_path('2026-09-11', 'checks', base)))


class DealEventAndSnapshotTests(QueueTestMixin, TestCase):
    '''4d deal event：契約判別（只帶 deal 欄的 GenericHouseItem）、shard → deals 分區；
    4c snapshot：DB bootstrap 的 carry 欄對應、snapshotfold（前日缺→昨日由 DB 摺出、
    今日 provisional：list 覆蓋／detail 全欄覆蓋／deal event 勝／已關閉無訊號不攜帶）、
    同日重跑冪等。'''

    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {'TWRH_RAW_BUCKET': ''})
        self.env.start()
        self.vendor = Vendor.objects.get(name=VENDOR_NAME)
        y, m, d = (int(x) for x in TEST_DATE.split('-'))
        self.day = date(y, m, d)
        self.yesterday = self.day - timedelta(days=1)

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def at(self, day, hour):
        return timezone.make_aware(datetime(day.year, day.month, day.day, hour))

    def write_rows(self, tree, run, rows, date_str):
        from rental import artifacts
        with mock.patch.dict(os.environ, {'TWRH_RUN_ID': run}):
            writer = artifacts.ShardWriter(tree)
            for row in rows:
                writer.append({'vendor': '591', 'date': date_str, 'run': run, **row})
            writer.close()

    def test_deal_event_contract_and_pack(self):
        from django.core.management import call_command
        from rental import artifacts, contracts
        deal_time = self.at(self.yesterday, 0)
        # key 組＝scrapy_twrh deal_mixin 實際 yield 的（含 vendor_house_url；
        # 2026-09-12 首夜就是少這個 key 判假、整晚事件沒落 shard）
        item = {'vendor': VENDOR_NAME, 'vendor_house_id': 'h1', 'vendor_house_url': 'u',
                'deal_status': 2, 'deal_time': deal_time, 'n_day_deal': 3}
        self.assertTrue(contracts.is_deal_event(item))
        self.assertTrue(contracts.is_deal_event({k: v for k, v in item.items()
                                                 if k != 'vendor_house_url'}))
        self.assertFalse(contracts.is_deal_event({**item, 'monthly_price': 1}))   # detail 列
        self.assertFalse(contracts.is_deal_event({**item, 'deal_status': 0}))
        row = contracts.deal_event_row('591', 'h1', TEST_DATE, 'run', timezone.now(), deal_time, 3)
        self.assertEqual(set(row), {name for name, _ in contracts.DEAL_EVENT_FIELDS})
        self.write_rows('deals', 'run', [{k: v for k, v in row.items() if k not in ('vendor', 'date', 'run')}], TEST_DATE)
        call_command('artifactpack', '--tree', 'deals', '--date', TEST_DATE, '--no-upload')
        rows = artifacts.read_deal_events('591', TEST_DATE)
        self.assertEqual([(r['vendor_house_id'], r['deal_time'], r['n_day_deal']) for r in rows],
                         [('h1', deal_time, 3)])
        self.assertTrue(os.path.exists(artifacts.partition_path('deals', '591', TEST_DATE, 'run')))

    def seed_yesterday_db(self):
        '''昨日 DB 狀態：h1 昨日 detail（在 list）、h2 只在 list（合成列、指紋在上次 detail 後變過）、
        h3 DEAL（三天沒在 list）。'''
        from rental.models import HouseEtc
        y = self.yesterday
        old = self.at(y - timedelta(days=9), 3)
        h1 = House.objects.create(vendor=self.vendor, vendor_house_id='h1', monthly_price=10000,
                                  detail_crawled_at=self.at(y, 3), list_crawled_at=self.at(y, 2))
        House.objects.filter(pk=h1.pk).update(created=old)
        HouseEtc.objects.create(house=h1, vendor=self.vendor, vendor_house_id='h1',
                                list_dict={'price': '10000', 'title': 't1'})
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='h1', year=y.year, month=y.month,
                               day=y.day, hour=0, monthly_price=10000, floor_ping=20.0,
                               crawled_at=self.at(y, 3), list_crawled_at=self.at(y, 2))
        h2 = House.objects.create(vendor=self.vendor, vendor_house_id='h2', monthly_price=7000,
                                  detail_crawled_at=self.at(y - timedelta(days=5), 3),
                                  list_crawled_at=self.at(y, 2), list_fingerprint_changed_at=self.at(y, 2))
        HouseEtc.objects.create(house=h2, vendor=self.vendor, vendor_house_id='h2',
                                list_dict={'price': '7500', 'title': 't2'})
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='h2', year=y.year, month=y.month,
                               day=y.day, hour=0, monthly_price=7500, is_synthesized=True,
                               list_crawled_at=self.at(y, 2))
        House.objects.create(vendor=self.vendor, vendor_house_id='h3', deal_status=enums.DealStatusType.DEAL,
                             deal_time=self.at(y, 0), n_day_deal=4, list_crawled_at=self.at(y - timedelta(days=3), 2))
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='h3', year=y.year, month=y.month,
                               day=y.day, hour=0, deal_status=enums.DealStatusType.DEAL,
                               deal_time=self.at(y, 0), n_day_deal=4)
        return old

    def test_bootstrap_rows_carry_fields(self):
        from rental import contracts, snapshot_db
        created = self.seed_yesterday_db()
        by = {r['vendor_house_id']: r for r in snapshot_db.bootstrap_rows(self.vendor, self.yesterday)}
        self.assertEqual(sorted(by), ['h1', 'h2', 'h3'])
        fp1 = contracts.list_fingerprint({'price': '10000', 'title': 't1'})
        self.assertEqual((by['h1']['source'], by['h1']['last_detail_at'], by['h1']['last_fingerprint'],
                          by['h1']['fingerprint_at_last_detail'], by['h1']['days_absent'],
                          by['h1']['first_seen_at'], by['h1']['floor_ping'], by['h1']['deal_source']),
                         ('detail', self.at(self.yesterday, 3), fp1, fp1, 0, created, 20.0, None))
        self.assertEqual((by['h2']['source'], by['h2']['fingerprint_at_last_detail'], by['h2']['monthly_price']),
                         ('list', None, 7500))          # 指紋在上次 detail 後變過 → None（＝視為已變）
        self.assertIsNotNone(by['h2']['last_fingerprint'])
        self.assertEqual((by['h3']['source'], by['h3']['deal_status'], by['h3']['deal_source'],
                          by['h3']['days_absent'], by['h3']['n_day_deal']),
                         ('carry', int(enums.DealStatusType.DEAL), 'deals', 3, 4))
        self.assertEqual(set(by['h1']), {name for name, _ in contracts.SNAPSHOT_FIELDS})

    def test_snapshotfold_bootstraps_yesterday_and_folds_today(self):
        from django.core.management import call_command
        from rental import artifacts, contracts, snapshot
        self.seed_yesterday_db()
        t_list, t_detail, t_deal = self.at(self.day, 2), self.at(self.day, 3), self.at(self.day, 6)
        self.write_rows('list', 'run', [
            {'vendor_house_id': 'h1', 'seen_at': t_list.isoformat(), 'fingerprint': 'newfp',
             'monthly_price': 12000}], TEST_DATE)
        self.write_rows('parsed', 'run', [
            {'vendor_house_id': 'h2', 'crawled_at': t_detail.isoformat(), 'deal_status': 0,
             'monthly_price': 8000, 'floor_ping': 9.5}], TEST_DATE)
        self.write_rows('deals', 'run', [
            {'vendor_house_id': 'h1', 'seen_at': t_deal.isoformat(),
             'deal_time': self.at(self.day, 0).isoformat(), 'n_day_deal': 2}], TEST_DATE)
        for tree in ('list', 'parsed', 'deals'):
            call_command('artifactpack', '--tree', tree, '--date', TEST_DATE, '--no-upload')

        call_command('snapshotfold', '--date', TEST_DATE, '--no-upload')
        prev = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', self.yesterday.isoformat())}
        self.assertEqual(sorted(prev), ['h1', 'h2', 'h3'])           # 昨日由 DB bootstrap
        today = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', TEST_DATE)}
        self.assertEqual(sorted(today), ['h1', 'h2'])                # h3 已關閉且無訊號：不攜帶
        h1, h2 = today['h1'], today['h2']
        self.assertEqual((h1['source'], h1['monthly_price'], h1['floor_ping'], h1['last_fingerprint'],
                          h1['fingerprint_at_last_detail'], h1['last_seen_at'], h1['days_absent']),
                         ('list', 12000, 20.0, 'newfp', prev['h1']['last_fingerprint'], t_list, 0))
        self.assertEqual((h1['deal_status'], h1['deal_time'], h1['n_day_deal'], h1['deal_source']),
                         (snapshot.DEAL, self.at(self.day, 0), 2, 'deals'))
        self.assertEqual((h2['source'], h2['monthly_price'], h2['floor_ping'], h2['last_detail_at'],
                          h2['fingerprint_at_last_detail'], h2['days_absent'], h2['first_seen_at']),
                         ('detail', 8000, 9.5, t_detail, prev['h2']['last_fingerprint'], 1, prev['h2']['first_seen_at']))
        self.assertEqual(h1['date'], TEST_DATE)
        self.assertEqual(set(h1), {name for name, _ in contracts.SNAPSHOT_FIELDS})

        # 同日重跑：前日仍缺、昨日已在 → 不動昨日；今日重摺結果相同
        call_command('snapshotfold', '--date', TEST_DATE, '--no-upload')
        again = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', TEST_DATE)}
        self.assertEqual(again, today)
        # --bootstrap 明確重摺某日
        call_command('snapshotfold', '--bootstrap', '--date', self.yesterday.isoformat(), '--no-upload')
        self.assertEqual(len(artifacts.read_snapshot('591', self.yesterday.isoformat())), 3)

    def test_snapshotfold_recovers_late_deal_from_earlier_snapshot(self):
        '''4d：今日 deals 事件的戶不在昨日 snapshot、但在前幾天的 snapshot 有 → 補值。'''
        from django.core.management import call_command
        from rental import artifacts, snapshot
        y = self.yesterday
        before2 = y - timedelta(days=2)
        gone = snapshot._blank('591', 'gone', before2.isoformat())
        gone.update({'monthly_price': 6500, 'floor_ping': 9.0, 'source': 'detail', 'deal_status': snapshot.NOT_FOUND,
                     'first_seen_at': self.at(before2 - timedelta(days=10), 1), 'last_seen_at': self.at(before2, 1),
                     'days_absent': 0})
        artifacts.write_snapshot([gone], '591', before2.isoformat())
        artifacts.write_snapshot([snapshot._blank('591', 'other', y.isoformat())], '591', y.isoformat())
        deal_time = self.at(y, 0)
        self.write_rows('deals', 'run', [{'vendor_house_id': 'gone', 'seen_at': self.at(self.day, 6).isoformat(),
                                          'deal_time': deal_time.isoformat(), 'n_day_deal': 12,
                                          'event_version': 1}], TEST_DATE)
        call_command('artifactpack', '--tree', 'deals', '--date', TEST_DATE, '--no-upload')
        with mock.patch.dict(os.environ, {'TWRH_DEAL_LOOKBACK_DAYS': '7'}):
            call_command('snapshotfold', '--date', TEST_DATE, '--no-upload')
        today = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', TEST_DATE)}
        self.assertEqual((today['gone']['deal_status'], today['gone']['deal_source'], today['gone']['n_day_deal'],
                          today['gone']['monthly_price'], today['gone']['floor_ping'], today['gone']['days_absent']),
                         (snapshot.DEAL, 'deals', 12, 6500, 9.0, 3))
        self.assertEqual(today['gone']['first_seen_at'], gone['first_seen_at'])
        # 回看窗只有 1 天 → 找不到 → 空白 deal-only 列
        with mock.patch.dict(os.environ, {'TWRH_DEAL_LOOKBACK_DAYS': '1'}):
            call_command('snapshotfold', '--date', TEST_DATE, '--no-upload')
        today = {r['vendor_house_id']: r for r in artifacts.read_snapshot('591', TEST_DATE)}
        self.assertEqual((today['gone']['deal_status'], today['gone']['monthly_price']), (snapshot.DEAL, None))

    def test_backfill_past_day_from_ts_without_house_carry(self):
        '''#11：過去日由 HouseTS 摺出，carry 欄只留該日列推得出的；已存在的天跳過、--force 才覆寫。'''
        from django.core.management import call_command
        from rental import artifacts, snapshot_db
        created = self.seed_yesterday_db()
        y = self.yesterday
        by = {r['vendor_house_id']: r for r in snapshot_db.bootstrap_rows(self.vendor, y, carry='ts')}
        # h1 該日 detail：source 仍判得出（House.detail_crawled_at 落在該日），但 last_detail_at／指紋不填
        self.assertEqual((by['h1']['source'], by['h1']['last_detail_at'], by['h1']['last_fingerprint'],
                          by['h1']['fingerprint_at_last_detail'], by['h1']['last_seen_at'],
                          by['h1']['days_absent'], by['h1']['first_seen_at'], by['h1']['floor_ping']),
                         ('detail', None, None, None, self.at(y, 2), 0, created, 20.0))
        self.assertEqual((by['h2']['source'], by['h2']['last_fingerprint'], by['h2']['days_absent']),
                         ('list', None, 0))
        # h3 該日不在 list：缺席天數對過去日不可知 → None（bootstrap 模式會由 House 現值算 3）
        self.assertEqual((by['h3']['source'], by['h3']['deal_source'], by['h3']['days_absent'],
                          by['h3']['last_seen_at'], by['h3']['n_day_deal']),
                         ('carry', 'deals', None, None, 4))
        with self.assertRaises(ValueError):
            snapshot_db.bootstrap_rows(self.vendor, y, carry='nope')

        y_str = y.isoformat()
        call_command('snapshotfold', '--backfill', '--from', y_str, '--to', y_str, '--no-upload')
        rows = artifacts.read_snapshot('591', y_str)
        self.assertEqual(sorted(r['vendor_house_id'] for r in rows), ['h1', 'h2', 'h3'])
        # 再跑：已存在 → 跳過（檔案 mtime 不變）；--force 才重寫
        path = artifacts.snapshot_path('591', y_str)
        mtime = os.path.getmtime(path)
        call_command('snapshotfold', '--backfill', '--from', y_str, '--to', y_str, '--no-upload')
        self.assertEqual(os.path.getmtime(path), mtime)
        HouseTS.objects.filter(vendor_house_id='h3').delete()
        call_command('snapshotfold', '--backfill', '--from', y_str, '--to', y_str, '--no-upload', '--force')
        self.assertEqual(sorted(r['vendor_house_id'] for r in artifacts.read_snapshot('591', y_str)), ['h1', 'h2'])
        # 沒給日期／--to 早於 --from 都要擋
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('snapshotfold', '--backfill', '--no-upload')
        with self.assertRaises(CommandError):
            call_command('snapshotfold', '--backfill', '--from', TEST_DATE, '--to', y_str, '--no-upload')


class DealDeriveTests(TestCase):
    '''4d 推導側（rental/deals.py，無 DB）：deals 事件勝、inferred 語意、n_day_deal 推導、
    關閉多日後才進成交列表的戶由 closed_rows 補值。'''

    def test_n_day_deal_inferred_uses_taipei_calendar_days(self):
        from datetime import datetime, timezone, timedelta
        from rental.deals import n_day_deal_inferred
        tpe = timezone(timedelta(hours=8))
        first = datetime(2026, 1, 10, 23, 30, tzinfo=tpe)          # 台北 1/10 深夜（UTC 1/10 15:30）
        deal = datetime(2026, 1, 13, 0, 0, tzinfo=tpe)             # vendor 給的成交日 1/13 00:00+08
        self.assertEqual(n_day_deal_inferred(deal, first), 3)
        self.assertEqual(n_day_deal_inferred(deal, first.astimezone(timezone.utc)), 3)   # 同一刻、不同 tz
        self.assertEqual(n_day_deal_inferred(first, deal), 0)                            # 倒過來夾 0
        self.assertIsNone(n_day_deal_inferred(None, first))
        self.assertIsNone(n_day_deal_inferred('2026-01-13', first))                     # 非 datetime（測試用字串）

    def test_apply_deal_semantics(self):
        from datetime import datetime, timezone, timedelta
        from rental.deals import apply_deal, deal_state, DEAL
        tpe = timezone(timedelta(hours=8))
        first = datetime(2026, 1, 10, tzinfo=tpe)
        # 事件勝：vendor 三欄照抄
        row = {'deal_status': 0, 'first_seen_at': first, 'deal_source': None, 'n_day_deal': None, 'deal_time': None}
        apply_deal(row, {'deal_time': datetime(2026, 1, 12, tzinfo=tpe), 'n_day_deal': 5})
        self.assertEqual(deal_state(row), {'deal_status': DEAL, 'deal_time': datetime(2026, 1, 12, tzinfo=tpe),
                                           'n_day_deal': 5, 'deal_source': 'deals'})
        # 事件沒給 n_day_deal → 推導補、來源仍是 deals
        row = {'deal_status': 0, 'first_seen_at': first}
        apply_deal(row, {'deal_time': datetime(2026, 1, 12, tzinfo=tpe), 'n_day_deal': None})
        self.assertEqual((row['deal_source'], row['n_day_deal']), ('deals', 2))
        # 昨日 sticky 帶來的 DEAL、無來源標記 → inferred，n_day_deal 由 deal_time − first_seen_at 推
        row = {'deal_status': DEAL, 'deal_time': datetime(2026, 1, 14, tzinfo=tpe), 'first_seen_at': first,
               'deal_source': None, 'n_day_deal': None}
        apply_deal(row, None)
        self.assertEqual((row['deal_source'], row['n_day_deal']), ('inferred', 4))
        # 已有 vendor n_day_deal 的 DEAL 不動
        row = {'deal_status': DEAL, 'deal_time': datetime(2026, 1, 14, tzinfo=tpe), 'first_seen_at': first,
               'deal_source': 'deals', 'n_day_deal': 9}
        apply_deal(row, None)
        self.assertEqual((row['deal_source'], row['n_day_deal']), ('deals', 9))
        # 非 DEAL 完全不碰
        row = {'deal_status': 1, 'deal_source': None, 'n_day_deal': None}
        apply_deal(row, None)
        self.assertEqual(deal_state(row), {'deal_status': 1, 'deal_time': None, 'n_day_deal': None, 'deal_source': None})

    def test_fold_recovers_closed_house_for_late_deal_event(self):
        from rental.snapshot import fold, DEAL, NOT_FOUND
        stub = lambda hid, at: {'vendor_house_id': hid, 'seen_at': at, 'fingerprint': 'f', 'monthly_price': 9000}
        d1 = fold([], [stub('g', 'T1')], [{'vendor_house_id': 'g', 'crawled_at': 'T1d', 'deal_status': 0,
                                           'monthly_price': 9000, 'floor_ping': 8.0}], [], '2026-01-15')
        # 1/16 detail 404 → NOT_FOUND（保留最後已知值）；1/17 無訊號 → 不攜帶
        d2 = fold(d1, [], [{'vendor_house_id': 'g', 'crawled_at': 'T2d', 'deal_status': NOT_FOUND}], [], '2026-01-16')
        self.assertEqual((d2[0]['deal_status'], d2[0]['monthly_price']), (NOT_FOUND, 9000))
        d3 = fold(d2, [], [], [], '2026-01-17')
        self.assertEqual(d3, [])
        event = [{'vendor_house_id': 'g', 'seen_at': 'T4', 'deal_time': 'D', 'n_day_deal': 3}]
        # 1/18 成交事件到，昨日 snapshot 無此戶：沒給 closed_rows → 空白 deal-only 列
        blank = fold(d3, [], [], event, '2026-01-18')[0]
        self.assertEqual((blank['deal_status'], blank['deal_source'], blank['monthly_price'], blank['first_seen_at']),
                         (DEAL, 'deals', None, None))
        # 給 closed_rows（1/16 那列）→ 租金／坪數／首見沿用，days_absent 依日期差遞推（1/16 列 1 ＋ 1/16→1/18 差 2）
        got = fold(d3, [], [], event, '2026-01-18', closed_rows={'g': d2[0]})[0]
        self.assertEqual((got['deal_status'], got['deal_source'], got['n_day_deal'], got['monthly_price'],
                          got['floor_ping'], got['first_seen_at'], got['source'], got['days_absent']),
                         (DEAL, 'deals', 3, 9000, 8.0, 'T1', 'carry', 3))   # 1/15 最後在 list：16、17、18 三天缺席
        # closed_rows 只對「有事件且昨日不在」的戶生效：無事件的戶不會因此復活
        self.assertEqual(fold(d3, [], [], [], '2026-01-18', closed_rows={'g': d2[0]}), [])


class SnapshotCheckTests(QueueTestMixin, TestCase):
    '''4c 對帳：snapshot parquet 對 HouseTS（parsed 欄＋狀態欄）與 House（carry 欄）。
    DB bootstrap 摺出的 snapshot 對回 DB 必 AGREE；戶集合差異、欄位差、狀態差、carry 差
    各進各的桶；檢查過去日時 carry 只對 TS 可推的兩項。'''

    def setUp(self):
        super().setUp()
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='twrh-snapshotcheck-')
        self.env = mock.patch.dict(os.environ, {'TWRH_ARTIFACT_DIR': self.tmp, 'TWRH_RAW_BUCKET': ''})
        self.env.start()
        self.vendor = Vendor.objects.get(name=VENDOR_NAME)
        y, m, d = (int(x) for x in TEST_DATE.split('-'))
        self.day = date(y, m, d)

    def tearDown(self):
        import shutil
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def at(self, day, hour):
        return timezone.make_aware(datetime(day.year, day.month, day.day, hour))

    def seed_db(self):
        from django.contrib.gis.geos import Point
        from rental.models import Author, HouseEtc
        d = self.day
        author = Author.objects.create(truth='0912')
        h1 = House.objects.create(vendor=self.vendor, vendor_house_id='h1', monthly_price=15000,
                                  detail_crawled_at=self.at(d, 3), list_crawled_at=self.at(d, 2))
        HouseEtc.objects.create(house=h1, vendor=self.vendor, vendor_house_id='h1',
                                list_dict={'price': '15000', 'title': 't1'})
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='h1', year=d.year, month=d.month,
                               day=d.day, hour=0, monthly_price=15000, imgs=['a'], author=author,
                               rough_coordinate=Point(25.03, 121.56, srid=4326),
                               crawled_at=self.at(d, 3), list_crawled_at=self.at(d, 2))
        House.objects.create(vendor=self.vendor, vendor_house_id='h2', monthly_price=7000,
                             detail_crawled_at=self.at(d - timedelta(days=4), 3),
                             list_crawled_at=self.at(d - timedelta(days=1), 2))
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='h2', year=d.year, month=d.month,
                               day=d.day, hour=0, monthly_price=7000, is_synthesized=True)
        House.objects.create(vendor=self.vendor, vendor_house_id='h3', deal_status=enums.DealStatusType.DEAL,
                             deal_time=self.at(d, 0), n_day_deal=4, list_crawled_at=self.at(d - timedelta(days=2), 2))
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='h3', year=d.year, month=d.month,
                               day=d.day, hour=0, deal_status=enums.DealStatusType.DEAL,
                               deal_time=self.at(d, 0), n_day_deal=4)

    def write_snapshot(self, rows):
        from rental import artifacts
        artifacts.write_snapshot(rows, '591', TEST_DATE)

    def run_check(self, *args):
        from contextlib import redirect_stdout
        from io import StringIO
        from django.core.management import call_command
        import json
        out = StringIO()
        with redirect_stdout(out):
            call_command('snapshotcheck', '--date', TEST_DATE, *args)
        line = [l for l in out.getvalue().splitlines() if l.startswith('snapshotcheck: ')][0]
        verdict, _, payload = line[len('snapshotcheck: '):].partition(' — ')
        return verdict, json.loads(payload)

    def test_bootstrap_snapshot_agrees_and_diffs_are_bucketed(self):
        from rental import snapshot, snapshot_db
        self.seed_db()
        rows = snapshot_db.bootstrap_rows(self.vendor, self.day)
        self.write_snapshot(rows)
        verdict, report = self.run_check()
        self.assertEqual((verdict, report['carry_mode'], report['matched'],
                          report['snapshot_rows'], report['db_rows']),
                         ('AGREE', 'house', 3, 3, 3), report)

        # 欄位差／狀態差／carry 差／戶集合差各進各的桶
        HouseTS.objects.filter(vendor_house_id='h1').update(monthly_price=16000)
        HouseTS.objects.filter(vendor_house_id='h3').update(deal_status=enums.DealStatusType.OPENED)
        House.objects.filter(vendor_house_id='h2').update(list_crawled_at=self.at(self.day, 5))
        HouseTS.objects.create(vendor=self.vendor, vendor_house_id='h4', year=self.day.year,
                               month=self.day.month, day=self.day.day, hour=0, is_synthesized=True)
        extra = snapshot._blank('591', 'h5', TEST_DATE)
        extra['source'] = 'carry'
        self.write_snapshot(rows + [extra])
        verdict, report = self.run_check()
        self.assertEqual(verdict, 'DIFF')
        self.assertEqual(report['mismatch_by_field'], {'monthly_price': 1})
        self.assertEqual(report['state_mismatch'], {'deal_status': 1})
        self.assertEqual(set(report['carry_mismatch']), {'last_seen_at', 'days_absent'})
        self.assertEqual(report['only_db'], {'opened/synthesized': 1})
        self.assertEqual(report['only_snapshot'], {'carry': 1})
        with self.assertRaises(SystemExit):
            self.run_check('--strict')

    def test_past_day_checks_carry_from_ts_only(self):
        from rental import snapshot_db
        self.seed_db()
        rows = snapshot_db.bootstrap_rows(self.vendor, self.day)
        # 昨日 final 的情境：House 現值已被「今日」改寫，carry 只對 TS 可推的兩項
        House.objects.filter(vendor_house_id='h1').update(
            detail_crawled_at=self.at(self.day + timedelta(days=1), 3),
            list_crawled_at=self.at(self.day + timedelta(days=1), 2))
        self.write_snapshot(rows)
        tomorrow = (self.day + timedelta(days=1)).isoformat()
        with mock.patch.dict(os.environ, {'TWRH_TARGET_DATE': tomorrow}):
            verdict, report = self.run_check()
        self.assertEqual((verdict, report['carry_mode']), ('AGREE', 'ts'), report)
        rows[0]['days_absent'] = 2      # h1 在 list 卻 days_absent≠0
        self.write_snapshot(rows)
        with mock.patch.dict(os.environ, {'TWRH_TARGET_DATE': tomorrow}):
            verdict, report = self.run_check()
        self.assertEqual((verdict, report['carry_mismatch']), ('DIFF', {'days_absent': 1}))

    def test_missing_snapshot_skips(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        with redirect_stdout(out):
            call_command('snapshotcheck', '--date', TEST_DATE)
        self.assertIn('no snapshot for', out.getvalue())


class ManifestPartitionsTests(TestCase):
    '''manifest 並列輸出：四份 manifest 各帶由分區檔算出的 partitions 節（每 vendor 一塊）；
    缺分區＝該 vendor 不出現；算失敗只留 error。'''
    fixtures = ['vendors']

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='twrh-manifest-partitions-')
        self.env = mock.patch.dict(os.environ, {'TWRH_ARTIFACT_DIR': self.tmp, 'TWRH_RAW_BUCKET': ''})
        self.env.start()

    def tearDown(self):
        import shutil
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_rows(self, tree, run, rows):
        from rental import artifacts
        with mock.patch.dict(os.environ, {'TWRH_RUN_ID': run}):
            writer = artifacts.ShardWriter(tree)
            for row in rows:
                writer.append({'vendor': '591', 'date': TEST_DATE, 'run': run, **row})
            writer.close()

    def test_partitions_alongside_db_counts(self):
        from django.core.management import call_command
        from rental import artifacts, snapshot
        from crawlerrequest import manifests
        y, m, d = (int(x) for x in TEST_DATE.split('-'))
        now = timezone.now()
        deal_time = timezone.make_aware(datetime(y, m, d))
        self.write_rows('list', 'run', [
            {'vendor_house_id': 'a', 'seen_at': now.isoformat(), 'fingerprint': 'f'},
            {'vendor_house_id': 'b', 'seen_at': now.isoformat(), 'fingerprint': 'g'}])
        self.write_rows('list', 'sweep-0801', [
            {'vendor_house_id': 'a', 'seen_at': now.isoformat(), 'fingerprint': 'f'}])
        self.write_rows('parsed', 'run', [
            {'vendor_house_id': 'a', 'crawled_at': now.isoformat()},
            {'vendor_house_id': 'c', 'crawled_at': now.isoformat()}])   # 同戶同輪會去重，故用兩戶
        self.write_rows('deals', 'run', [
            {'vendor_house_id': 'b', 'seen_at': now.isoformat(),
             'deal_time': deal_time.isoformat(), 'n_day_deal': 2}])
        for tree in ('list', 'parsed', 'deals'):
            call_command('artifactpack', '--tree', tree, '--date', TEST_DATE, '--no-upload')
        s1 = snapshot._blank('591', 'a', TEST_DATE); s1['source'] = 'detail'
        s2 = snapshot._blank('591', 'b', TEST_DATE)
        s2.update({'source': 'list', 'deal_status': snapshot.DEAL, 'deal_source': 'deals'})
        artifacts.write_snapshot([s1, s2], '591', TEST_DATE)

        built = {}
        for path in manifests.build_all(date(y, m, d), base_dir=self.tmp):
            import json
            with open(path) as f:
                mf = json.load(f)
            built[mf['stage']] = mf
        self.assertEqual(built['list']['partitions']['591'],
                         {'n_stubs': 3, 'n_houses': 2, 'runs': ['run', 'sweep-0801']})
        self.assertEqual(built['detail']['partitions']['591'],
                         {'n_rows': 2, 'n_houses': 2, 'runs': ['run']})
        self.assertEqual(built['deals']['partitions']['591'],
                         {'n_events': 1, 'n_houses': 1, 'runs': ['run'], 'by_deal_date': {TEST_DATE: 1}})
        self.assertEqual(built['snapshot']['partitions']['591'],
                         {'n_total': 2, 'n_opened': 1, 'n_closed': 0, 'n_dealt': 1,
                          'by_source': {'detail': 1, 'list': 1}, 'by_deal_source': {'deals': 1}})
        # DB 版數字仍在（並列，不是取代）
        self.assertEqual(built['snapshot']['counts']['n_total'], 0)
        # 其他 vendor 無分區 → 不出現
        self.assertEqual(set(built['list']['partitions']), {'591'})

    def test_partitions_absent_is_empty(self):
        from crawlerrequest import manifests
        y, m, d = (int(x) for x in TEST_DATE.split('-'))
        self.assertEqual(manifests.build_snapshot_manifest(date(y, m, d))['partitions'], {})


class ItemHygieneTests(QueueTestMixin, TestCase):
    '''item_hygiene（schema 1.0 §1 P1／P3）：list 的 tag 版 facilities 不蓋 detail 的完整清單；
    detail 的 None rough_address 不蓋 list 給的街道級地址。pipeline 對 item 每個 key 都 setattr，
    所以擋法＝在 yield 前把 key 拿掉。'''

    def test_strip_functions_are_pure_and_key_scoped(self):
        from crawler.spiders.item_hygiene import strip_list_item, strip_detail_item
        from scrapy_twrh.items import GenericHouseItem
        li = GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='a', monthly_price=1,
                              facilities={'電梯': True}, rough_address='中山北路二段')
        self.assertIs(strip_list_item(li), li)
        self.assertNotIn('facilities', li)
        self.assertEqual((li['monthly_price'], li['rough_address']), (1, '中山北路二段'))
        # 沒帶 facilities 的 list item 也不炸
        strip_list_item(GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='b'))
        di = GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='a', rough_address=None,
                              facilities={'桌子': True, '冰箱': False})
        self.assertIs(strip_detail_item(di), di)
        self.assertNotIn('rough_address', di)
        self.assertEqual(di['facilities'], {'桌子': True, '冰箱': False})
        # detail 有值的地址保留（未來解析器補上時不被誤刪）
        di2 = GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='a', rough_address='忠孝東路')
        strip_detail_item(di2)
        self.assertEqual(di2['rough_address'], '忠孝東路')

    def test_pipeline_keeps_detail_facilities_and_list_address(self):
        from crawler.pipelines import CrawlerPipeline
        from crawler.spiders.item_hygiene import strip_list_item, strip_detail_item
        from scrapy_twrh.items import GenericHouseItem
        with mock.patch.dict(os.environ, {'TWRH_RAW_BUCKET': '', 'TWRH_RUN_ID': 'run', 'TWRH_RAW_SINK': '0'}):
            pipeline = CrawlerPipeline()
            detail_fac = {'桌子': True, '椅子': True, '冰箱': False}
            # list 先到：帶街道級地址與 tag 版 facilities
            pipeline.process_item(strip_list_item(GenericHouseItem(
                vendor=VENDOR_NAME, vendor_house_id='h', monthly_price=10000,
                rough_address='中山北路二段', facilities={'電梯': True})), None)
            # detail 到：完整家具清單、地址 None
            pipeline.process_item(strip_detail_item(GenericHouseItem(
                vendor=VENDOR_NAME, vendor_house_id='h', monthly_price=10000,
                rough_address=None, facilities=dict(detail_fac))), None)
            # 隔輪 list 又來（同日 sweep 或次日日跑都一樣）
            pipeline.process_item(strip_list_item(GenericHouseItem(
                vendor=VENDOR_NAME, vendor_house_id='h', monthly_price=10000,
                rough_address='中山北路二段', facilities={'電梯': True, '陽台': True})), None)
            pipeline.close_spider()
        house = House.objects.get(vendor_house_id='h')
        ts = HouseTS.objects.get(vendor_house_id='h')
        self.assertEqual((house.facilities, house.rough_address), (detail_fac, '中山北路二段'))
        self.assertEqual((ts.facilities, ts.rough_address), (detail_fac, '中山北路二段'))

    def test_spiders_strip_at_yield(self):
        '''接線驗證：list591 兩個 yield 點與 detail591 的 yield 點都經過 hygiene。'''
        from crawler.spiders.list591_spider import List591Spider
        from crawler.spiders.detail591_spider import Detail591Spider
        from scrapy_twrh.items import GenericHouseItem, RawHouseItem
        raw = RawHouseItem(house_id='h', raw=b'', dict={})
        gen = lambda: GenericHouseItem(vendor=VENDOR_NAME, vendor_house_id='h',
                                       facilities={'電梯': True}, rough_address=None)
        ls = List591Spider.__new__(List591Spider)
        ls.frontier_pages = 0
        ls.default_parse_list = lambda response: iter([raw, gen()])
        out = list(ls.parse_list_and_stop(None))
        self.assertNotIn('facilities', out[1])
        self.assertIs(out[0], raw)
        ds = Detail591Spider.__new__(Detail591Spider)
        ds.default_parse_detail = lambda response: iter([gen()])
        out = list(ds.parse_detail_and_done(None))
        self.assertNotIn('rough_address', out[0])
        self.assertEqual(out[0]['facilities'], {'電梯': True})
