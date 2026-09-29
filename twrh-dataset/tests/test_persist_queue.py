'''crawler/spiders/persist_queue（檔案 queue 版）：認領／釋放／batch／errback／狀態機。

歷史上 bug 密度最高的共用件——認領 race（#21）、batch 觸頂後繼續爬（2026-08-26）、
errback 斷餵（2026-09-05）、errback 列無人釋放。DB 時代這些語意鎖在 request_ts 列上；
S6 起同一組語意改對檔案 queue（seeds 檔＋每 worker 的終結檔）驗。
'''
import os
import unittest
from unittest import mock

import scrapy
from scrapy.http import TextResponse

from tests.helpers import (TEST_DATE, TempEnvTestCase, drain, make_queue, make_response,
                           terminals, worker_queue)


def exploding_parser(response):
    raise ValueError('boom')
    yield  # pragma: no cover


class GenAndClaimTests(TempEnvTestCase):
    '''種子建立與認領：seeds 檔／in_flight／範圍界定。'''

    def test_gen_persist_request_writes_unclaimed_seed(self):
        from crawlerrequest.enums import RequestType
        from rental import filequeue as fq
        q = make_queue()
        q.gen_persist_request({'id': 'h1'})
        q.close_files()

        self.assertEqual(q.request_type, RequestType.DETAIL)
        self.assertEqual(fq.load_seeds('591', TEST_DATE, 'detail')[0], {'id=h1': {'id': 'h1'}})
        self.assertTrue(os.path.exists(fq.seeds_path('591', TEST_DATE, 'detail', 'run')))
        self.assertEqual(fq.remaining('591', TEST_DATE, 'detail'), {'id=h1': ({'id': 'h1'}, 0)})
        self.assertEqual(terminals(), {})
        self.assertEqual(q.progress_tracker.total, 1)
        self.assertTrue(q.has_request())

    def test_next_request_claims_exactly_one(self):
        from crawler.spiders.persist_queue import QueueItem
        q = make_queue()
        q.gen_persist_request({'id': 'h1'})
        q.gen_persist_request({'id': 'h2'})

        request = q.next_request()

        self.assertIsInstance(request, scrapy.Request)
        item = request.meta['db_request']
        self.assertIsInstance(item, QueueItem)
        self.assertEqual((item.key, item.seed, item.attempts), ('id=h1', {'id': 'h1'}, 1))
        self.assertEqual(request.callback, q.parser_wrapper)
        self.assertEqual(list(q.in_flight), ['id=h1'])
        self.assertEqual(q.n_live_spider, 1)
        self.assertEqual([k for k, _s, _a in q.pending], ['id=h2'])   # 另一項仍可認領
        self.assertEqual(terminals(), {})                              # 認領不落終結行

    def test_next_request_returns_none_on_empty_queue(self):
        q = make_queue()
        self.assertIsNone(q.next_request())
        self.assertFalse(q.has_request())

    def test_next_request_skips_items_terminated_by_others(self):
        from rental import filequeue as fq
        make_queue().gen_persist_request({'id': 'h1'})
        make_queue().gen_persist_request({'id': 'h2'})
        other = fq.TerminalWriter('591', TEST_DATE, 'detail', 'run', 'worker-other')
        other.append('id=h1', 'done', 1)
        other.append('id=h2', 'dead', 3, error='http_403')
        other.close()

        self.assertIsNone(make_queue().next_request())

    def test_two_shards_claim_distinct_items(self):
        seeder = make_queue()
        seeder.gen_persist_request({'id': 'h1'})
        seeder.gen_persist_request({'id': 'h2'})
        seeder.close_files()
        q1, q2 = worker_queue(0, 2), worker_queue(1, 2)

        a, b = drain(q1), drain(q2)

        self.assertEqual((len(a), len(b)), (1, 1))
        self.assertNotEqual(a[0].key, b[0].key)

    def test_queue_length_caps_in_memory_requests(self):
        q = make_queue()
        q.gen_persist_request({'id': 'h1'})
        q.n_live_spider = q.queue_length

        self.assertIsNone(q.next_request())
        self.assertEqual(q.in_flight, {})        # 沒有項被偷偷認領

    def test_claim_scoped_to_date_vendor_and_type(self):
        from rental import filequeue as fq
        for vendor, day, type_name in (('591', '2026-01-14', 'detail'),   # 昨天的殘留
                                       ('591', TEST_DATE, 'list'),        # 同日另一型
                                       ('好房網', TEST_DATE, 'detail')):   # 另一 vendor
            w = fq.SeedsWriter(vendor, day, type_name, 'run')
            w.append('x', {'id': 'x'})
            w.close()

        q = make_queue()
        self.assertIsNone(q.next_request())
        self.assertFalse(q.has_request())


class ReleaseClaimsTests(TempEnvTestCase):
    '''收工釋放：只放自己的、不碰別人的（多 task 並跑的前提）。'''

    def test_release_only_own_claims(self):
        seeder = make_queue()
        seeder.gen_persist_request({'id': 'h1'})
        seeder.gen_persist_request({'id': 'h2'})
        seeder.close_files()
        q1, q2 = worker_queue(0, 2), worker_queue(1, 2)
        r1, r2 = q1.next_request(), q2.next_request()

        released = q1.release_claims()

        self.assertEqual(released, 1)
        t = terminals()
        own = r1.meta['db_request'].key
        self.assertEqual((t[own]['status'], t[own]['error']), ('failed', 'released:unfinished'))
        self.assertNotIn(r2.meta['db_request'].key, t)
        self.assertIn(r2.meta['db_request'].key, q2.in_flight)
        self.assertFalse(os.path.exists(q1.heartbeat.path))      # 收工刪心跳
        self.assertTrue(os.path.exists(q2.heartbeat.path))

    def test_released_item_is_claimable_again(self):
        q1 = make_queue()
        q1.gen_persist_request({'id': 'h1'})
        q1.next_request()
        q1.release_claims()

        q2 = make_queue()
        request = q2.next_request()
        self.assertIsNotNone(request)
        self.assertEqual(request.meta['db_request'].attempts, 2)   # attempts 跨輪累計


class ParserWrapperTests(TempEnvTestCase):
    '''完成／解析失敗／batch 觸頂的儲存語意。'''

    @staticmethod
    def claim_one(q, seed_id='h1'):
        q.gen_persist_request({'id': seed_id})
        return q.next_request().meta['db_request']

    def test_success_terminalizes_item(self):
        q = make_queue(batch_size=1)  # batch=1：完成後不進補貨迴圈
        item = self.claim_one(q)

        list(q.parser_wrapper(make_response(item)))

        t = terminals()[item.key]
        self.assertEqual((t['status'], t['attempts']), ('done', 1))
        self.assertEqual(q.progress_tracker.completed, 1)
        self.assertEqual(q.n_live_spider, 0)
        self.assertEqual(q.in_flight, {})

    def test_parse_error_marks_failed_signals_and_retries_next_pass(self):
        from crawler import signals as twrh_signals
        q = make_queue(batch_size=5, parse_response=exploding_parser)
        sent = []
        q.spider = mock.Mock()
        q.spider.crawler.signals.send_catch_log.side_effect = lambda sig, **kw: sent.append(sig)
        item = self.claim_one(q)

        yielded = list(q.parser_wrapper(make_response(item, status=500)))

        self.assertEqual([r for r in yielded if isinstance(r, scrapy.Request)], [])
        t = terminals()[item.key]
        self.assertEqual((t['status'], t['error']), ('failed', 'parse_error:ValueError'))
        self.assertEqual(sent, [twrh_signals.parse_error])
        self.assertEqual(q.progress_tracker.completed, 0)
        self.assertEqual(q.n_live_spider, 0)
        # 檔案 queue 的重試在下一輪（batch 重啟／收尾補掃）：attempts 累計
        again = make_queue().next_request().meta['db_request']
        self.assertEqual((again.key, again.attempts), (item.key, 2))

    def test_parse_error_at_max_attempts_goes_dead(self):
        q = make_queue(batch_size=5, parse_response=exploding_parser)
        q.max_attempts = 1
        item = self.claim_one(q)

        yielded = list(q.parser_wrapper(make_response(item)))

        self.assertEqual([r for r in yielded if isinstance(r, scrapy.Request)], [])
        t = terminals(max_attempts=1)[item.key]
        self.assertEqual((t['status'], t['error']), ('dead', 'parse_error:ValueError'))
        self.assertEqual(q.release_claims(), 0)

    def test_last_status_recorded(self):
        # parser 什麼都沒回（沒完成、沒炸）：收工釋放時帶上最後的 http 狀態
        q = make_queue(batch_size=1, parse_response=lambda r: iter([]))
        item = self.claim_one(q)
        list(q.parser_wrapper(make_response(item, status=403)))
        self.assertNotIn(item.key, terminals())
        q.release_claims()
        t = terminals()[item.key]
        self.assertEqual((t['status'], t['error']), ('failed', 'released:unfinished'))
        from tests.helpers import read_jsonl
        from rental import filequeue as fq
        lines = read_jsonl(os.path.join(fq.terminals_dir('591', TEST_DATE, 'detail', 'run'),
                                        q.worker_name + '.jsonl'))
        self.assertEqual([line['http'] for line in lines], [403])

    def test_batch_limit_stops_replenishment(self):
        q = make_queue(batch_size=1)
        item1 = self.claim_one(q, 'h1')
        q.gen_persist_request({'id': 'h2'})  # 排隊中、觸頂後不應被認領

        yielded = list(q.parser_wrapper(make_response(item1)))

        self.assertTrue(q.is_batch_complete())
        self.assertEqual([r for r in yielded if isinstance(r, scrapy.Request)], [])
        self.assertNotIn('id=h2', q.in_flight)
        self.assertNotIn('id=h2', terminals())

    def test_suspended_replenish_loop_stops_after_batch_limit(self):
        '''補貨迴圈懸掛在 yield 中間、恢復時已觸頂 → 不得繼續認領
        （2026-08-26 batch 13 實測：觸頂後多爬 2,559 筆的機制）。'''
        q = make_queue(batch_size=2)
        item1 = self.claim_one(q, 'h1')
        item2 = self.claim_one(q, 'h2')
        q.gen_persist_request({'id': 'h3'})
        q.gen_persist_request({'id': 'h4'})

        # 完成 h1（1/2），補貨迴圈 yield 出 h3 的請求後懸掛
        gen1 = q.parser_wrapper(make_response(item1))
        first_refill = next(gen1)
        self.assertEqual(first_refill.meta['db_request'].seed, {'id': 'h3'})
        # 完成 h2（2/2）→ 觸頂
        list(q.parser_wrapper(make_response(item2)))
        self.assertTrue(q.is_batch_complete())
        # 恢復懸掛中的 gen1：不得再把 h4 認領出來
        remainder = list(gen1)

        self.assertEqual([r for r in remainder if isinstance(r, scrapy.Request)], [])
        self.assertNotIn('id=h4', q.in_flight)

    def test_below_batch_limit_replenishes_from_queue(self):
        q = make_queue(batch_size=5)
        item1 = self.claim_one(q, 'h1')
        q.gen_persist_request({'id': 'h2'})

        yielded = list(q.parser_wrapper(make_response(item1)))

        followups = [r for r in yielded if isinstance(r, scrapy.Request)]
        self.assertEqual(len(followups), 1)
        self.assertEqual(followups[0].meta['db_request'].seed, {'id': 'h2'})


class StateMachineTests(TempEnvTestCase):
    '''終結狀態機：errback 必寫終結狀態、attempts 上限轉 dead。'''

    @staticmethod
    def claim(q, seed_id='h1'):
        q.gen_persist_request({'id': seed_id})
        return q.next_request()

    def fail_via_errback(self, q, request, exception):
        '''觸發 errback。名額先填滿：errback 會補餵（2026-09-05 修正），要觀察 failed
        中間態就不能留名額給它；回傳前把名額歸零。'''
        from twisted.python.failure import Failure
        failure = Failure(exception)
        failure.request = request
        q.n_live_spider = q.queue_length + 1
        replenished = q.handle_errback(failure)
        self.assertEqual(replenished, [])                     # 名額滿 → 不補餵
        self.assertEqual(q.n_live_spider, q.queue_length)      # errback 釋放了一個名額
        q.n_live_spider = 0
        return request.meta['db_request']

    def test_http_errback_writes_failed_with_classification(self):
        from scrapy.spidermiddlewares.httperror import HttpError
        q = make_queue()
        request = self.claim(q)
        response = TextResponse(url=request.url, status=403, body=b'', request=request)

        item = self.fail_via_errback(q, request, HttpError(response))

        self.assertEqual(terminals()[item.key]['status'], 'failed')
        self.assertEqual(terminals()[item.key]['error'], 'http_403')
        self.assertEqual(item.last_status, 403)
        self.assertEqual(q.in_flight, {})

    def test_errback_replenishes_from_queue(self):
        '''收尾整批 errback 時不能斷餵：errback 要回傳補認領的 Request。'''
        q = make_queue()
        for i in range(3):
            q.gen_persist_request({'id': 'r{}'.format(i)})
        first = q.next_request()
        q.n_live_spider = q.queue_length   # 模擬名額滿、其餘尚未認領
        failure = mock.Mock()
        failure.request = first
        failure.check.return_value = False
        failure.type = ValueError

        replenished = q.handle_errback(failure)

        self.assertGreaterEqual(len(replenished), 1)
        self.assertTrue(all(isinstance(r, scrapy.Request) for r in replenished))
        t = terminals()[first.meta['db_request'].key]
        self.assertEqual((t['status'], t['error']), ('failed', 'ValueError'))

    def test_network_errback_writes_type_name(self):
        from twisted.internet.error import TimeoutError as TxTimeoutError
        q = make_queue()
        item = self.fail_via_errback(q, self.claim(q), TxTimeoutError())
        self.assertEqual(terminals()[item.key]['error'], 'TimeoutError')

    def test_errback_without_queue_item_is_noop(self):
        from twisted.python.failure import Failure
        q = make_queue()
        failure = Failure(ValueError('no meta'))
        failure.request = scrapy.Request(url='https://example.com/robots.txt')
        self.assertIsNone(q.handle_errback(failure))   # 不炸即可（robots 等非 queue 請求）
        self.assertEqual(terminals(), {})

    def test_attempts_exhaustion_turns_dead(self):
        from twisted.internet.error import TimeoutError as TxTimeoutError
        q = make_queue()
        q.max_attempts = 2
        request = self.claim(q)

        # 第一次失敗：attempts=1 < 2 → failed，下一輪可再認領
        item = self.fail_via_errback(q, request, TxTimeoutError())
        self.assertEqual(terminals(max_attempts=2)[item.key]['status'], 'failed')
        q2 = make_queue()
        q2.max_attempts = 2
        request2 = q2.next_request()
        self.assertIsNotNone(request2)
        self.assertEqual(request2.meta['db_request'].attempts, 2)
        self.fail_via_errback(q2, request2, TxTimeoutError())

        self.assertEqual(terminals(max_attempts=2)[item.key]['status'], 'dead')
        # dead 不再被認領
        q3 = make_queue()
        q3.max_attempts = 2
        self.assertIsNone(q3.next_request())
        self.assertFalse(q3.has_request())

    def test_release_claims_escalates_exhausted_to_dead(self):
        q = make_queue()
        q.max_attempts = 1
        item = self.claim(q).meta['db_request']  # attempts=1 == max，收工釋放時直接 dead

        self.assertEqual(q.release_claims(), 1)
        t = terminals(max_attempts=1)[item.key]
        self.assertEqual((t['status'], t['error']), ('dead', 'released:unfinished'))

    def test_done_items_survive_release_claims(self):
        q = make_queue(batch_size=1)
        item = self.claim(q).meta['db_request']
        list(q.parser_wrapper(make_response(item)))

        self.assertEqual(q.release_claims(), 0)
        self.assertEqual(terminals()[item.key]['status'], 'done')

    def test_remaining_work_excludes_terminal_items(self):
        q = make_queue(batch_size=1)
        q.gen_persist_request({'id': 'h1'})
        q.gen_persist_request({'id': 'h2'})
        request = q.next_request()
        list(q.parser_wrapper(make_response(request.meta['db_request'])))

        self.assertEqual(q.get_total_count(), 1)  # DONE 不算剩餘工作


class FileClaimTests(TempEnvTestCase):
    '''S4a 起的檔案認領：分片對「當日全部 seeds」位置輪分，worker 任意時刻重啟都算出同一片、
    永不重疊；收尾單 worker（count=1）補掃殘餘。'''

    def test_shards_are_disjoint_stable_across_restart_and_mopped_up(self):
        from crawler.spiders.persist_queue import QueueItem
        from rental import filequeue as fq
        primary = worker_queue(0, 1)
        for k in ('a', 'b', 'c', 'd', 'e', 'f', 'g'):
            primary.gen_persist_request({'id': k})
        primary.close_files()
        keys = list(fq.load_seeds('591', TEST_DATE, 'detail')[0])
        self.assertEqual(len(keys), 7)
        # 三個 worker 各自分片：兩兩不重疊、聯集＝全部（#21 並發認領的檔案版）
        w = [worker_queue(i, 3) for i in range(3)]
        claimed = [drain(q) for q in w]
        sets = [{it.key for it in c} for c in claimed]
        self.assertEqual(sets[0] | sets[1] | sets[2], set(keys))
        self.assertFalse(sets[0] & sets[1] or sets[1] & sets[2] or sets[0] & sets[2])
        self.assertTrue(all(isinstance(it, QueueItem) and it.attempts == 1
                            for c in claimed for it in c))
        # worker 0 做完自己的第一個、其餘放掉（模擬 batch 收工）；worker 1 整個死掉（不釋放）
        first = claimed[0][0]
        list(w[0].parser_wrapper(make_response(first)))
        w[0].release_claims()
        t = terminals()
        self.assertEqual(t[first.key]['status'], 'done')
        for it in claimed[0][1:]:
            self.assertEqual((t[it.key]['status'], t[it.key]['error']), ('failed', 'released:unfinished'))
        # worker 0 重啟（同 index／count）：分片一致，只剩自己未完成的（不含 worker 1／2 的）
        again = drain(worker_queue(0, 3))
        self.assertEqual({it.key for it in again}, sets[0] - {first.key})
        self.assertTrue(all(it.attempts == 2 for it in again))   # attempts 跨輪累計
        # 收尾補掃：count=1 拿到所有未終結的
        mop = worker_queue(0, 1)
        rest = drain(mop)
        self.assertEqual({it.key for it in rest}, set(keys) - {first.key})
        for it in rest:
            list(mop.parser_wrapper(make_response(it)))
        mop.release_claims()
        r = fq.reconcile('591', TEST_DATE, 'detail')
        self.assertEqual((r['seeds'], r['done'], r['dead'], r['residue']), (7, 7, 0, 0))

    def test_failures_accumulate_attempts_then_dead_and_release(self):
        from rental import filequeue as fq
        q = worker_queue(0, 1, parse_response=exploding_parser)
        q.max_attempts = 2
        q.gen_persist_request({'id': 'x'})
        q.gen_persist_request({'id': 'y'})
        it = q.next_request().meta['db_request']
        list(q.parser_wrapper(make_response(it, status=500)))     # attempts 1 → failed
        t = terminals(max_attempts=2)[it.key]
        self.assertEqual((t['status'], t['error']), ('failed', 'parse_error:ValueError'))
        q2 = worker_queue(0, 1, parse_response=exploding_parser)
        q2.max_attempts = 2
        items = drain(q2)                                         # x（attempts 2）與 y
        by = {i.key: i for i in items}
        self.assertEqual(by[it.key].attempts, 2)
        list(q2.parser_wrapper(make_response(by[it.key])))        # 達上限 → dead
        self.assertEqual(terminals(max_attempts=2)[it.key]['status'], 'dead')
        q2.release_claims()                                       # y 在手上未做 → failed
        self.assertEqual(terminals(max_attempts=2)['id=y']['error'], 'released:unfinished')
        r = fq.reconcile('591', TEST_DATE, 'detail', max_attempts=2)
        self.assertEqual((r['seeds'], r['done'], r['dead'], r['residue']), (2, 0, 1, 1))
        self.assertTrue(q2.has_request())
        self.assertEqual(q2.get_total_count(), 1)
        self.assertFalse(os.path.exists(q2.heartbeat.path))

    def test_same_seed_dedups_by_key(self):
        from rental import filequeue as fq
        q = worker_queue(0, 1)
        q.gen_persist_request({'id': 'h1'})
        q.gen_persist_request({'id': 'h1'})                   # 重排同一戶：同 key、去重
        q.gen_persist_request({'id': 'h2'})
        items = drain(q)
        self.assertEqual(sorted(i.key for i in items), ['id=h1', 'id=h2'])
        self.assertTrue(all(i.id == i.key for i in items))
        list(q.parser_wrapper(make_response(items[0])))
        q.release_claims()
        r = fq.reconcile('591', TEST_DATE, 'detail')
        self.assertEqual((r['seeds'], r['done'], r['residue'], r['duplicate_seed_lines']), (2, 1, 1, 1))

    def test_list_seeds_are_per_run_but_detail_seeds_dedup_across_runs(self):
        '''S4b 首日（2026-09-15）：日跑與每輪 sweep 的 list 種子（縣市, page 0）內容相同，
        純內容 key 讓 08:01 之後每輪都「takes 0」。list key 帶 run；detail 仍跨 run 去重。'''
        from rental import filequeue as fq
        seed = {'id': 1, 'name': 'A', 'page': 0}
        q = worker_queue(0, 1, is_list=True)
        q.gen_persist_request(seed)
        it = q.next_request().meta['db_request']
        self.assertEqual(it.key, 'run#id=1|name=A|page=0')
        list(q.parser_wrapper(make_response(it)))           # 日跑做完
        q.release_claims()
        d = worker_queue(0, 1)
        d.gen_persist_request({'id': 'h1'})
        list(d.parser_wrapper(make_response(d.next_request().meta['db_request'])))
        d.release_claims()
        with mock.patch.dict(os.environ, {'TWRH_RUN_ID': 'sweep-0501'}):
            q2 = worker_queue(0, 1, is_list=True)
            q2.gen_persist_request(seed)                    # 前緣掃描：同縣市 page 0
            items = drain(q2)
            self.assertEqual([i.key for i in items], ['sweep-0501#id=1|name=A|page=0'])
            q2.release_claims()
            d2 = worker_queue(0, 1)
            d2.gen_persist_request({'id': 'h1'})            # 同一戶 detail：仍去重、不再抓
            self.assertEqual(drain(d2), [])
        r = fq.reconcile('591', TEST_DATE, 'list')
        self.assertEqual((r['seeds'], r['done'], r['residue']), (2, 1, 1))
        self.assertEqual(fq.reconcile('591', TEST_DATE, 'detail')['seeds'], 1)

    def test_dynamic_seeds_after_load_and_has_seed(self):
        q = worker_queue(0, 1, is_list=True)
        q.gen_persist_request({'id': 1, 'name': 'A', 'page': 0})
        self.assertTrue(q.has_seed(seed__id=1))
        self.assertFalse(q.has_seed(seed__id=2))
        first = q.next_request()                                   # 載入分片
        self.assertEqual(first.meta['db_request'].seed['page'], 0)
        q.gen_persist_request({'id': 1, 'name': 'A', 'page': 1})   # 翻頁：生種子的就是消費者
        nxt = q.next_request()
        self.assertEqual(nxt.meta['db_request'].seed['page'], 1)
        self.assertIsNone(q.next_request())

    def test_reconcile_counts_every_terminal_path(self):
        '''done／parse error 達上限 dead／認領未做 release 成 dead／從未認領 residue。'''
        from rental import filequeue as fq
        q = make_queue(batch_size=1)
        q.max_attempts = 1
        for k in ('a', 'b', 'c', 'd'):
            q.gen_persist_request({'id': k})
        r1 = q.next_request()
        list(q.parser_wrapper(make_response(r1.meta['db_request'])))       # a：done
        q.parse_response = exploding_parser
        r2 = q.next_request()
        list(q.parser_wrapper(make_response(r2.meta['db_request'])))       # b：dead
        q.next_request()                                                   # c：認領不處理
        q.release_claims()                                                 # → dead
        r = fq.reconcile('591', TEST_DATE, 'detail', max_attempts=1)
        self.assertEqual((r['seeds'], r['done'], r['dead'], r['residue']), (4, 1, 2, 1))
        self.assertEqual(r['orphan_terminals'], 0)

    def test_seed_ids_today_reads_file_seeds(self):
        q = make_queue()
        q.gen_persist_request({'id': 'h1'})
        q.gen_persist_request({'id': 'h2'})
        self.assertEqual(q.seed_ids_today(), {'h1', 'h2'})

    def test_db_queue_source_is_refused(self):
        with mock.patch.dict(os.environ, {'TWRH_QUEUE_SOURCE': 'db'}):
            with self.assertRaises(ValueError):
                make_queue()

    def test_start_early_and_target_date_pin_bucket(self):
        q = make_queue()
        self.assertEqual((q.date_str, q.short, q.type_name), (TEST_DATE, '591', 'detail'))
        os.environ.pop('TWRH_TARGET_DATE')
        from datetime import datetime
        from rental import tz
        late = datetime(2026, 1, 15, 22, 30, tzinfo=tz.TPE)
        with mock.patch('crawler.spiders.persist_queue.timezone.localtime', return_value=late):
            self.assertEqual(make_queue(start_early=True).date_str, '2026-01-16')


if __name__ == '__main__':
    unittest.main()
