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
from datetime import timedelta
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
from crawlerrequest.enums import RequestType  # noqa: E402
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

    def tearDown(self):
        if self._old_target_date is None:
            os.environ.pop('TWRH_TARGET_DATE', None)
        else:
            os.environ['TWRH_TARGET_DATE'] = self._old_target_date
        super().tearDown()

    # --- 終結語意斷言（1-1 只改這裡） ---

    def assert_completed(self, row_id):
        '''完成＝刪列（現制）。1-1 後：列留存、status=DONE。'''
        self.assertFalse(RequestTS.objects.filter(id=row_id).exists())

    def assert_retriable_failure(self, row_id):
        '''失敗列仍在、可被之後的認領撿走（現制：release 後 owner 歸零）。

        1-1 後：status=FAILED、attempts+1、error 有分類。'''
        row = RequestTS.objects.get(id=row_id)
        self.assertIsNone(row.owner)
        self.assertFalse(row.is_pending)


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
        self.assertFalse(row.is_pending)
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
        self.assertTrue(claimed.is_pending)
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
        RequestTS.objects.update(owner='someone-else', is_pending=True)

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
        self.assert_retriable_failure(r1.meta['db_request'].id)
        other = RequestTS.objects.get(id=r2.meta['db_request'].id)
        self.assertEqual(other.owner, q2.spider_id)
        self.assertTrue(other.is_pending)

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

    def test_parse_error_keeps_row_for_retry(self):
        def exploding_parser(response):
            raise ValueError('boom')
            yield  # pragma: no cover

        q = make_queue(batch_size=1, parse_response=exploding_parser)
        row = self._claim_one(q)

        list(q.parser_wrapper(make_response(row)))

        # 現制：列還在、掛在 owner 上，收工靠 release_claims 放回
        self.assertTrue(RequestTS.objects.filter(id=row.id).exists())
        self.assertEqual(q.progress_tracker.completed, 0)
        q.release_claims()
        self.assert_retriable_failure(row.id)

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
