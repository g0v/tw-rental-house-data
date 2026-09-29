'''detail 種子：純函數（rental/seeding.py）、檔案判準（seeds_from_files）、已知物件
（rental/known.py），以及 detail591 的 full／diff／new／seed_only／consume_only 接線。'''
import os
import unittest
from datetime import date, timedelta
from unittest import mock

from tests.helpers import (TEST_DATE, YESTERDAY, TempEnvTestCase, snapshot_row, write_latest,
                           write_stubs)


def _now():
    from rental import tz
    return tz.now()


class SeedFunctionTests(unittest.TestCase):
    '''四類（stale／指紋／缺席／回列）＋skip，無 I/O。'''

    def stub(self, hid, fp='same', at=None):
        return {'vendor_house_id': hid, 'fingerprint': fp, 'seen_at': (at or _now()).isoformat()}

    def test_state_from_snapshot_maps_carry_columns(self):
        from rental.seeding import state_from_snapshot, select_seeds
        now = _now()
        rows = [
            {'vendor_house_id': 'old', 'deal_status': 0,
             'last_detail_at': now - timedelta(days=30), 'fingerprint_at_last_detail': 'x'},
            {'vendor_house_id': 'moved', 'deal_status': 0,
             'last_detail_at': now - timedelta(days=1), 'fingerprint_at_last_detail': 'was'},
            {'vendor_house_id': 'dealt', 'deal_status': 2,
             'last_detail_at': now - timedelta(days=30), 'fingerprint_at_last_detail': 'x'},
        ]
        state = state_from_snapshot(rows)
        self.assertEqual(sorted(state), ['moved', 'old'])
        self.assertEqual(state['old'].detail_crawled_at, rows[0]['last_detail_at'])
        self.assertEqual(state['moved'].fingerprint_at_last_detail, 'was')
        self.assertTrue(state['old'].open)

        stubs = [self.stub('old', 'x'), self.stub('moved', 'now-different')]
        r = select_seeds(stubs, {'old', 'moved'}, state, now, refresh_days=7)
        self.assertEqual(r.stale, {'old'})
        self.assertEqual(r.fingerprint, {'moved'})
        self.assertEqual(r.seeds, {'old', 'moved'})

    def test_house_back_after_dropping_out_of_snapshot_is_seeded(self):
        '''關閉後掉出 snapshot、之後重新上架的戶：今日在 list 而手上沒狀態 → 當「在架、從未
        detail」排一次（2026-09-17 dry-run：785 戶只有 DB 軌排）。'''
        from rental.seeding import state_from_snapshot, select_seeds
        now = _now()
        rows = [{'vendor_house_id': 'known', 'deal_status': 0,
                 'last_detail_at': now - timedelta(days=1), 'fingerprint_at_last_detail': 'same'}]
        stubs = [self.stub('known', 'same'), self.stub('came-back', 'whatever')]

        bare = state_from_snapshot(rows)
        self.assertNotIn('came-back', bare)
        self.assertEqual(select_seeds(stubs, {'known', 'came-back'}, bare, now).seeds, set())

        state = state_from_snapshot(rows, seen_today={s['vendor_house_id'] for s in stubs})
        self.assertTrue(state['came-back'].open)
        self.assertIsNone(state['came-back'].detail_crawled_at)
        r = select_seeds(stubs, {'known', 'came-back'}, state, now)
        self.assertEqual(r.stale, {'came-back'})
        self.assertEqual(r.seeds, {'came-back'})

    def test_four_seed_classes_and_skip(self):
        from rental.seeding import HouseState, select_seeds
        now = _now()
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
        self.assertEqual(sorted(r.seeds), ['absent', 'fp_carry', 'fp_legacy', 'new', 'returned', 'stale'])
        self.assertEqual(r.n_open, 9)
        self.assertEqual(r.n_in_list, 9)          # dealt 也在 list（stub 不看狀態）
        self.assertEqual(r.skipped, 8 - 5)        # open∩today 8 − seeds∩today 5
        self.assertNotIn('fresh_returned', r.seeds)   # 回列但 12 小時內 detail 過＝同輪已處理

    def test_latest_fingerprint_wins_across_runs(self):
        from rental.seeding import HouseState, select_seeds, latest_fingerprints
        now = _now()
        today = [self.stub('h', fp='old', at=now - timedelta(hours=5)),
                 self.stub('h', fp='new', at=now - timedelta(hours=1))]
        self.assertEqual(latest_fingerprints(today), {'h': 'new'})
        state = {'h': HouseState(open=True, detail_crawled_at=now - timedelta(days=1),
                                 fingerprint_at_last_detail='old')}
        self.assertEqual(select_seeds(today, {'h'}, state, now).fingerprint, {'h'})

    def test_new_mode_seeds_only_never_detailed(self):
        from rental.seeding import HouseState, select_new_seeds
        state = {'a': HouseState(open=True), 'b': HouseState(open=True, detail_crawled_at=_now()),
                 'c': HouseState(open=False)}
        self.assertEqual(select_new_seeds([self.stub('a'), self.stub('b'), self.stub('c'),
                                           self.stub('x')], state), {'a'})

    def test_refresh_jitter_is_per_house_and_bounded(self):
        '''stale 門檻 refresh±jitter 由 house_id 雜湊決定：分散、有界、jitter 0＝舊制。'''
        from rental import seeding
        from rental.seeding import HouseState, select_seeds
        now = _now()
        ids = ['h{:03d}'.format(i) for i in range(60)]
        crawled = {hid: now - timedelta(days=4.75 + (i % 11) * 0.5) for i, hid in enumerate(ids)}
        thresholds = {seeding.refresh_days_for(hid, 7, 2) for hid in ids}
        self.assertTrue(thresholds <= {5, 6, 7, 8, 9} and len(thresholds) >= 4, thresholds)
        self.assertEqual(seeding.refresh_days_for('h001', 7, 0), 7)
        self.assertEqual(seeding.refresh_days_for('h001', 7, 2), seeding.refresh_days_for('h001', 7, 2))
        state = {hid: HouseState(open=True, detail_crawled_at=at) for hid, at in crawled.items()}
        stubs = [self.stub(hid) for hid in ids]
        jittered = select_seeds(stubs, set(ids), state, now, refresh_days=7, refresh_jitter_days=2).stale
        self.assertEqual(jittered, {hid for hid in ids if seeding.is_stale(hid, crawled[hid], now, 7, 2)})
        plain = select_seeds(stubs, set(ids), state, now, refresh_days=7).stale
        self.assertEqual(plain, {hid for hid in ids if crawled[hid] < now - timedelta(days=7)})
        self.assertNotEqual(jittered, plain)


class SeedsFromFilesTests(TempEnvTestCase):
    '''S1：整套判準走檔案（今日 list stub＋昨日 snapshot 的 carry 欄）。材料不齊回 None＋reason，
    讓呼叫端退回全量——不自己找替代來源。'''

    def setUp(self):
        super().setUp()
        self.day = date.fromisoformat(TEST_DATE)
        self.now = _now()

    def snapshot_rows(self, rows):
        from rental import artifacts
        out = [snapshot_row(hid, YESTERDAY, deal_status=status, last_detail_at=detail_at,
                            fingerprint_at_last_detail=fp_at_detail)
               for hid, detail_at, fp_at_detail, status in rows]
        artifacts.write_snapshot(out, '591', YESTERDAY)

    def call(self):
        from rental import seeding
        return seeding.seeds_from_files('591', self.day, self.now, refresh_days=7)

    def test_missing_materials_return_none_with_reason(self):
        result, meta = self.call()
        self.assertIsNone(result)
        self.assertIn('no list stubs', meta['reason'])

        write_stubs(self, [('a', 'fp')], seen_at=self.now)
        result, meta = self.call()
        self.assertIsNone(result)                       # 昨日沒有全量 run 分區
        self.assertIn('no full-run', meta['reason'])

        # 昨日只有 sweep 分區也不算：前緣子集當「昨日在列」會把幾乎全部判成回列
        write_stubs(self, [('a', 'fp')], date_str=YESTERDAY, run='sweep-0501', seen_at=self.now)
        result, meta = self.call()
        self.assertIsNone(result)
        self.assertIn('no full-run', meta['reason'])

        write_stubs(self, [('a', 'fp')], date_str=YESTERDAY, seen_at=self.now)
        result, meta = self.call()
        self.assertIsNone(result)                       # 昨日 snapshot 還沒有
        self.assertIn('no snapshot', meta['reason'])

    def test_four_classes_from_files(self):
        old = self.now - timedelta(days=30)
        recent = self.now - timedelta(days=1)
        write_stubs(self, [('stale', 'fp'), ('moved', 'was'), ('quiet', 'fp')],
                    date_str=YESTERDAY, seen_at=self.now)
        write_stubs(self, [('stale', 'fp'), ('moved', 'now-different'), ('quiet', 'fp'), ('back', 'fp')],
                    seen_at=self.now)
        self.snapshot_rows([
            ('stale', old, 'fp', 0),
            ('moved', recent, 'was', 0),
            ('quiet', recent, 'fp', 0),
            ('gone-2d', recent, 'fp', 0),
            ('dealt', old, 'fp', 2),
        ])
        result, meta = self.call()
        self.assertIsNotNone(result)
        self.assertEqual(result.stale, {'stale', 'back'})
        self.assertEqual(result.fingerprint, {'moved'})
        self.assertEqual(result.absent, {'gone-2d'})
        self.assertEqual(result.returned, {'back'})
        self.assertEqual(result.seeds, {'stale', 'moved', 'gone-2d', 'back'})
        self.assertEqual(meta['yesterday_ids'], 3)


class KnownHousesTests(TempEnvTestCase):
    '''「這戶見過沒、上次 detail 何時」＝總表 latest(昨日)＋今日 stub（含 scratch）。'''

    def test_known_houses_from_latest_and_stubs(self):
        from rental import known
        at = _now()
        write_latest({'old': {'deal_status': 0, 'last_detail_at': at},
                      'closed': {'deal_status': 1, 'last_detail_at': at}})
        write_stubs(self, ['old', 'new1'])
        k = known.load('591', TEST_DATE)
        self.assertEqual((k.base_date, k.stub_days), (YESTERDAY, [TEST_DATE]))
        self.assertEqual(k.ids, {'old', 'closed', 'new1'})
        self.assertEqual((k.state['old'].open, k.state['old'].detail_crawled_at), (True, at))
        self.assertFalse(k.state['closed'].open)
        self.assertEqual((k.state['new1'].open, k.state['new1'].detail_crawled_at), (True, None))
        self.assertIn('new1', k)
        k.add('seen-on-page')
        self.assertIn('seen-on-page', k)

    def test_falls_back_to_older_latest_plus_gap_stubs(self):
        '''昨夜 latest stage 沒跑成：往回找最近一份總表，把之後每一天的 stub 都併進來。'''
        from rental import known
        write_latest({'old': {'deal_status': 0}}, date_str='2026-01-12')
        write_stubs(self, ['gap'], date_str='2026-01-14')
        write_stubs(self, ['today'])
        k = known.load('591', TEST_DATE)
        self.assertEqual(k.base_date, '2026-01-12')
        self.assertEqual(k.ids, {'old', 'gap', 'today'})
        self.assertEqual(k.stub_days, ['2026-01-14', TEST_DATE])

    def test_no_latest_uses_lookback_stubs_including_scratch(self):
        from rental import known
        from tests.helpers import write_shard
        write_shard('list', [{'vendor_house_id': 'unpacked', 'seen_at': _now().isoformat(),
                              'fingerprint': 'f'}])                       # scratch、尚未打包
        k = known.load('591', TEST_DATE)
        self.assertEqual((k.base_date, k.ids, k.stub_days), (None, {'unpacked'}, [TEST_DATE]))


class DetailSeedingTests(TempEnvTestCase):
    '''detail591 的種子接線：模式、同日重跑防呆、seed_only／consume_only、seed stamp。'''

    def spider(self, **kwargs):
        from crawler.spiders.detail591_spider import Detail591Spider
        spider = Detail591Spider(**kwargs)
        from tests.helpers import track
        track(spider.persist_queue)
        return spider

    def seeds(self):
        from rental import filequeue
        return sorted(s['id'] for s in filequeue.load_seeds('591', TEST_DATE, 'detail')[0].values())

    def start(self, spider, has_run_today=None):
        from crawler.spiders.persist_queue import PersistQueue
        if has_run_today is None:
            return list(spider.start_detail_requests())
        with mock.patch.object(PersistQueue, 'has_run_today', return_value=has_run_today):
            return list(spider.start_detail_requests())

    def known_world(self):
        write_latest({'old': {'deal_status': 0, 'last_detail_at': _now()},
                      'never': {'deal_status': 0},
                      'offlist': {'deal_status': 0},
                      'closed': {'deal_status': 1}})
        write_stubs(self, ['old', 'never', 'closed', 'brand-new'])

    def test_full_new_and_append_seed_sets(self):
        self.known_world()
        self.assertEqual(self.spider(seed_mode='new').gen_new_seeds(), ['brand-new', 'never'])
        self.assertEqual(self.spider().gen_full_seeds(), ['brand-new', 'never', 'offlist', 'old'])
        self.assertEqual(self.spider(append=True).gen_full_seeds(), ['brand-new', 'never', 'offlist'])

    def test_new_mode_skips_already_seeded_today_and_reads_scratch_stubs(self):
        from tests.helpers import write_shard
        write_latest({'new1': {'deal_status': 0}, 'offlist': {'deal_status': 0},
                      'old': {'deal_status': 0, 'last_detail_at': _now()},
                      'closed': {'deal_status': 1}})
        write_shard('list', [{'vendor_house_id': h, 'seen_at': '2026-01-15T01:00:00', 'fingerprint': 'f'}
                             for h in ('new1', 'new2', 'old', 'closed')])     # 尚未打包的 scratch
        spider = self.spider(seed_mode='new')
        self.assertEqual(spider.gen_new_seeds(), ['new1', 'new2'])        # offlist：不在今日 list
        spider.persist_queue.gen_persist_request({'id': 'new1'})
        self.assertEqual(spider.gen_new_seeds(), ['new2'])                # 同日已排過者不重排

    def test_new_mode_ignores_progress_guard(self):
        self.known_world()
        requests = self.start(self.spider(seed_mode='new'), has_run_today=True)
        self.assertEqual(len(requests), 2)
        self.assertEqual(self.seeds(), ['brand-new', 'never'])

    def test_regen_guard_when_queue_drained_same_day(self):
        '''queue 恰好耗盡＋今天跑過 → 不重生成（2026-08-26：55,943 筆重排）。'''
        self.known_world()
        self.assertEqual(self.start(self.spider(), has_run_today=True), [])
        self.assertEqual(self.seeds(), [])

    def test_seed_only_rerun_on_drained_day_does_not_regen(self):
        self.known_world()
        self.start(self.spider(seed_only=True), has_run_today=True)
        self.assertEqual(self.seeds(), [])

    def test_seed_only_generates_without_crawling(self):
        self.known_world()
        spider = self.spider(seed_only=True)
        self.assertEqual(self.start(spider, has_run_today=False), [])
        self.assertEqual(self.seeds(), ['brand-new', 'never', 'offlist', 'old'])
        self.assertTrue(spider.persist_queue.has_run_today())            # progress 檔建立
        # 同日重跑 seed_only：queue 還有東西 → 不重生
        self.start(self.spider(seed_only=True))
        from rental import filequeue
        self.assertEqual(filequeue.load_seeds('591', TEST_DATE, 'detail')[1], 0)

    def test_consume_only_never_generates(self):
        self.known_world()
        self.assertEqual(self.start(self.spider(consume_only=True), has_run_today=False), [])
        self.assertEqual(self.seeds(), [])

    def test_batch_limit_stops_start_requests(self):
        self.known_world()
        spider = self.spider(batch_size=1)
        gen = spider.start_detail_requests()
        with mock.patch('crawler.spiders.persist_queue.PersistQueue.has_run_today', return_value=False):
            first = next(gen)
        spider.persist_queue.progress_tracker.completed = 1        # 模擬 batch 額滿
        self.assertEqual(list(gen), [])
        self.assertEqual(first.meta['db_request'].attempts, 1)

    def test_diff_mode_seeds_from_files_and_leaves_now_stamp(self):
        '''spider 把算 stale 用的 now 與四類計數留在 <progress>/<date>.seed.json（seedcheck 時代的
        約定，檔案判準照留：可稽核當晚決策）。'''
        from rental import artifacts, seeding
        now = _now()
        write_stubs(self, [('h1', 'fp'), ('h2', 'fp')], date_str=YESTERDAY, seen_at=now)
        write_stubs(self, [('h1', 'fp'), ('h2', 'fp')], seen_at=now)
        artifacts.write_snapshot([
            snapshot_row('h1', YESTERDAY, deal_status=0, last_detail_at=now - timedelta(days=30),
                         fingerprint_at_last_detail='fp'),
            snapshot_row('h2', YESTERDAY, deal_status=0, last_detail_at=now - timedelta(days=1),
                         fingerprint_at_last_detail='fp')], '591', YESTERDAY)
        day = date.fromisoformat(TEST_DATE)
        before = _now()
        self.start(self.spider(seed_mode='diff', refresh_days=7, seed_only=True), has_run_today=False)
        self.assertEqual(self.seeds(), ['h1'])
        stamp_now, stamp = seeding.read_seed_stamp(day)
        self.assertTrue(before <= stamp_now <= _now())
        self.assertEqual((stamp['classes']['stale'], stamp['seeds']), (1, 1))
        self.assertTrue(seeding.seed_stamp_path(day).startswith(os.environ['TWRH_PROGRESS_DIR']))
        self.assertEqual(seeding.read_seed_stamp(day - timedelta(days=3000)), (None, None))

    def test_diff_mode_without_materials_falls_back_to_full(self):
        self.known_world()                                          # 沒有昨日 snapshot
        self.start(self.spider(seed_mode='diff', seed_only=True), has_run_today=False)
        self.assertEqual(self.seeds(), ['brand-new', 'never', 'offlist', 'old'])


if __name__ == '__main__':
    unittest.main()
