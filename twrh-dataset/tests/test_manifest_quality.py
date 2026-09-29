'''manifest（twrhctl/manifests.py：由分區檔算）、斷言引擎（crawlerrequest/quality.py）、
checks.json、monthreport 的月窗疊加、manifest／qualitycheck 指令。'''
import json
import os
import tempfile
import unittest
from datetime import date, datetime

from tests.helpers import (TEST_DATE, TempEnvTestCase, check_command, pack, run_command,
                           snapshot_row, write_shard, write_stubs)


def write_spec(path, checks, defaults=None):
    import yaml
    with open(path, 'w') as f:
        yaml.safe_dump({'version': 1,
                        'defaults': defaults or {'window': 30, 'min_history': 3, 'min_samples': 100},
                        'checks': checks}, f, allow_unicode=True)


class QualityEngineTests(unittest.TestCase):
    '''斷言引擎：min/max、near、樣本門檻、疊窗即算、缺席降級。'''

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='twrh-manifests-')
        self.dir = self._tmp.name
        self.assertions = os.path.join(self.dir, 'assertions.yaml')

    def tearDown(self):
        self._tmp.cleanup()

    def write_manifest(self, date_str, stage='detail', **payload):
        from crawlerrequest import manifest_files
        manifest_files.write_manifest({
            'schema': 1, 'stage': stage, 'date': date_str,
            'source': payload.pop('source', 'live'), **payload,
        }, base_dir=self.dir)

    def evaluate(self, date_str='2026-09-15'):
        from crawlerrequest import quality
        return quality.evaluate(date_str, assertions_path=self.assertions, base_dir=self.dir)

    @staticmethod
    def by_id(results, check_id):
        return next(r for r in results if r.check_id == check_id)

    def test_min_max_and_near(self):
        write_spec(self.assertions, [
            {'id': 'c.min', 'stage': 'detail', 'metric': 'queue.seeds', 'min': 1},
            {'id': 'c.max', 'stage': 'detail', 'metric': 'queue.residue', 'max': 0},
            {'id': 'c.near', 'stage': 'detail', 'metric': 'dist.median_floor', 'near': 4, 'tolerance': 1},
        ])
        self.write_manifest('2026-09-15', queue={'seeds': 0, 'residue': 3}, dist={'median_floor': 6})
        results = self.evaluate()
        for check_id in ('c.min', 'c.max', 'c.near'):
            r = self.by_id(results, check_id)
            self.assertFalse(r.ok)
            self.assertFalse(r.advisory)
            self.assertIn('FAIL', r.line())

    def test_small_sample_skips_hard_assert(self):
        write_spec(self.assertions, [
            {'id': 'c.dist', 'stage': 'detail', 'metric': 'dist.median_floor',
             'sample_n': 'dist.n', 'near': 4, 'tolerance': 1},
        ])
        self.write_manifest('2026-09-15', dist={'n': 50, 'median_floor': 99})
        r = self.by_id(self.evaluate(), 'c.dist')
        self.assertTrue(r.ok)
        self.assertIn('跳過', r.message)

    def test_rolling_median_bootstrap_then_drift(self):
        write_spec(self.assertions, [
            {'id': 'c.roll', 'stage': 'detail', 'metric': 'counts.n', 'rolling_median_within': 0.2},
        ])
        self.write_manifest('2026-09-15', counts={'n': 100})
        r = self.by_id(self.evaluate(), 'c.roll')
        self.assertTrue(r.ok)
        self.assertIn('bootstrap', r.message)
        for day in (11, 12, 13, 14):
            self.write_manifest('2026-09-{:02d}'.format(day), counts={'n': 100})
        self.write_manifest('2026-09-15', counts={'n': 50})
        r = self.by_id(self.evaluate(), 'c.roll')
        self.assertFalse(r.ok)
        self.assertFalse(r.advisory)
        self.write_manifest('2026-09-15', counts={'n': 90})
        self.assertTrue(self.by_id(self.evaluate(), 'c.roll').ok)

    def test_missing_metric_degrades_to_advisory(self):
        '''backfill manifest 缺 queue 節：不判紅、標 advisory。'''
        write_spec(self.assertions, [
            {'id': 'c.q', 'stage': 'detail', 'metric': 'queue.seeds', 'min': 1},
        ])
        self.write_manifest('2026-09-15', source='backfill', counts={'n': 5})
        r = self.by_id(self.evaluate(), 'c.q')
        self.assertFalse(r.ok)
        self.assertTrue(r.advisory)
        self.assertIn('backfill', r.message)

    def test_missing_manifest_is_hard_failure(self):
        write_spec(self.assertions, [
            {'id': 'c.q', 'stage': 'detail', 'metric': 'queue.seeds', 'min': 1},
        ])
        r = self.by_id(self.evaluate(), 'c.q')
        self.assertFalse(r.ok)
        self.assertFalse(r.advisory)
        self.assertIn('manifest 不存在', r.message)

    def test_committed_assertions_file_loads(self):
        from crawlerrequest import quality
        spec = quality.load_assertions()
        self.assertTrue(spec['checks'])
        self.assertTrue(all({'id', 'stage', 'metric'} <= set(c) for c in spec['checks']))


class ManifestChecksTests(unittest.TestCase):
    '''advisory 對帳判定落 manifests/<date>/checks.json：同 run 同 name 後寫者勝、不同 run 並存、缺檔回空殼。'''

    def test_record_and_load(self):
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

    def test_get_metric_dot_path(self):
        from crawlerrequest import manifest_files as mf
        m = {'queue': {'seeds': 3, 'errors': {}}, 'x': 1}
        self.assertEqual(mf.get_metric(m, 'queue.seeds'), 3)
        self.assertIsNone(mf.get_metric(m, 'queue.nope'))
        self.assertIsNone(mf.get_metric(m, 'x.y'))


class ManifestPartitionsTests(TempEnvTestCase):
    '''四份 manifest 由分區檔算（source: partitions），各帶 partitions 節（每 vendor 一塊；缺分區不出現）。'''

    def setUp(self):
        super().setUp()
        from twrhctl import manifests
        manifests._DayPartitions._cache.clear()
        self.manifests = manifests
        self.day = date.fromisoformat(TEST_DATE)

    def test_partitions_blocks(self):
        from rental import artifacts, snapshot, tz
        now = tz.now()
        deal_time = tz.make_aware(datetime(2026, 1, 15))
        write_shard('list', [{'vendor_house_id': 'a', 'seen_at': now.isoformat(), 'fingerprint': 'f'},
                             {'vendor_house_id': 'b', 'seen_at': now.isoformat(), 'fingerprint': 'g'}])
        write_shard('list', [{'vendor_house_id': 'a', 'seen_at': now.isoformat(), 'fingerprint': 'f'}],
                    run='sweep-0801')
        write_shard('parsed', [{'vendor_house_id': 'a', 'crawled_at': now.isoformat()},
                               {'vendor_house_id': 'c', 'crawled_at': now.isoformat()}])
        write_shard('deals', [{'vendor_house_id': 'b', 'seen_at': now.isoformat(),
                               'deal_time': deal_time.isoformat(), 'n_day_deal': 2}])
        for tree in ('list', 'parsed', 'deals'):
            pack(self, tree)
        artifacts.write_snapshot([
            snapshot_row('a', TEST_DATE, source='detail'),
            snapshot_row('b', TEST_DATE, source='list', deal_status=snapshot.DEAL, deal_source='deals')],
            '591', TEST_DATE)

        built = {}
        for path in self.manifests.build_all(self.day):
            with open(path) as f:
                mf = json.load(f)
            built[mf['stage']] = mf
        self.assertTrue(all(p.startswith(os.environ['TWRH_MANIFEST_DIR']) for p in
                            self.manifests.build_all(self.day)))
        self.assertEqual(built['list']['partitions']['591'],
                         {'n_stubs': 3, 'n_houses': 2, 'runs': ['run', 'sweep-0801']})
        self.assertEqual(built['detail']['partitions']['591'],
                         {'n_rows': 2, 'n_houses': 2, 'runs': ['run']})
        self.assertEqual(built['deals']['partitions']['591'],
                         {'n_events': 1, 'n_houses': 1, 'runs': ['run'], 'by_deal_date': {TEST_DATE: 1}})
        self.assertEqual(built['snapshot']['partitions']['591'],
                         {'n_total': 2, 'n_opened': 1, 'n_closed': 0, 'n_dealt': 1,
                          'by_source': {'detail': 1, 'list': 1}, 'by_deal_source': {'deals': 1}})
        self.assertEqual(built['snapshot']['counts']['n_total'], 2)
        self.assertEqual({mf['source'] for mf in built.values()}, {'partitions'})
        self.assertEqual(set(built['list']['partitions']), {'591'})     # 其他 vendor 無分區 → 不出現

    def test_partitions_absent_is_empty(self):
        m = self.manifests.build_snapshot_manifest(self.day)
        self.assertEqual((m['partitions'], m['counts']['n_total']), ({}, 0))

    def test_manifests_from_partitions(self):
        from rental import artifacts, tz
        at = tz.now()

        def row(hid, **kw):
            return snapshot_row(hid, TEST_DATE, **{'deal_status': 0, 'source': 'carry', **kw})
        artifacts.write_snapshot([
            row('d1', source='detail', floor=3, total_floor=5, monthly_price=9000, rough_lat=25.0,
                rough_address='台北市', first_seen_at=tz.make_aware(datetime(2026, 1, 15, 12))),
            row('l1', source='list', monthly_price=8000),
            row('c1'),                                    # 不在 list、沒 detail＝待確認關閉
            row('x1', deal_status=1, source='detail'),
            row('s1', deal_status=2, deal_time=at, n_day_deal=4, deal_source='deals'),
        ], '591', TEST_DATE)
        write_stubs(self, ['d1', 'l1'])
        write_shard('parsed', [{'vendor_house_id': 'd1', 'crawled_at': at.isoformat(), 'deal_status': 0,
                                'monthly_price': 9000, 'floor': 3, 'facilities': '{}', 'parsed_version': 2}])
        pack(self, 'parsed')
        lm = self.manifests.build_list_manifest(self.day)
        self.assertEqual(lm['source'], 'partitions')
        self.assertEqual(lm['counts']['n_in_list'], 2)
        self.assertEqual({k: lm['capture'][k] for k in (
            'n_open', 'n_open_in_list', 'n_confirmed_open', 'n_confirmed_open_in_list',
            'ratio', 'n_pending_absent')},
            {'n_open': 3, 'n_open_in_list': 2, 'n_confirmed_open': 1,
             'n_confirmed_open_in_list': 1, 'ratio': 1.0, 'n_pending_absent': 1})
        dm = self.manifests.build_detail_manifest(self.day)
        self.assertEqual(dm['counts'], {'n_crawled': 5, 'n_opened': 3, 'n_closed': 1,
                                        'n_dealt': 1, 'n_new_item': 1})
        # fill_rate 樣本＝parsed 分區（parser 的輸出），不是帶舊值的 snapshot
        self.assertEqual((dm['fill_rate']['n'], dm['fill_rate']['monthly_price'],
                          dm['fill_rate']['facilities'], dm['fill_rate']['rough_coordinate'],
                          dm['fill_rate']['rough_address']), (1, 1.0, 0.0, 0.0, 1.0))
        self.assertEqual(dm['dist']['n'], 3)
        self.assertEqual(self.manifests.build_deals_manifest(self.day)['counts']['n_events'], 1)
        sm = self.manifests.build_snapshot_manifest(self.day)
        self.assertEqual((sm['counts']['n_total'], sm['counts']['n_synthesized']), (5, 3))

    def test_deals_manifest_counts_events_by_deal_date(self):
        from rental import artifacts, snapshot, tz
        rows = [snapshot_row(hid, TEST_DATE, deal_status=snapshot.DEAL, source='carry',
                             deal_time=tz.make_aware(datetime(2026, 1, day)), n_day_deal=n)
                for hid, day, n in (('a', 15, 9), ('b', 14, 3), ('c', 14, 5))]
        rows.append(snapshot_row('open', TEST_DATE, deal_status=0, source='list'))
        artifacts.write_snapshot(rows, '591', TEST_DATE)
        m = self.manifests.build_deals_manifest(self.day)
        self.assertEqual(m['stage'], 'deals')
        self.assertEqual(m['counts']['n_events'], 3)
        self.assertEqual(m['by_deal_date'], {'2026-01-14': 2, '2026-01-15': 1})
        self.assertEqual(m['dist']['median_n_day_deal'], 5)
        self.assertEqual(m['queue']['seeds'], 0)

    def test_manifest_and_qualitycheck_commands(self):
        from crawlerrequest import manifest_files
        out = check_command(self, 'manifest', '--date', TEST_DATE, '--no-upload')
        self.assertIn('4 manifest(s) written', out)
        for stage in manifest_files.STAGES:
            self.assertIsNotNone(manifest_files.load_manifest(TEST_DATE, stage))
        spec = os.path.join(self.tmp, 'assertions.yaml')
        write_spec(spec, [{'id': 'snap.total', 'stage': 'snapshot', 'metric': 'counts.n_total', 'max': 0}])
        check_command(self, 'qualitycheck', '--date', TEST_DATE, '--assertions', spec)
        write_spec(spec, [{'id': 'snap.total', 'stage': 'snapshot', 'metric': 'counts.n_total', 'min': 1}])
        code, _out, err = run_command('qualitycheck', '--date', TEST_DATE, '--assertions', spec)
        self.assertEqual(code, 1, err)
        self.assertEqual(run_command('manifest', '--from', TEST_DATE)[0], 1)   # --from/--to 需成對


class MonthReportTests(unittest.TestCase):
    def test_stacks_daily_dists(self):
        from twrhctl.commands.monthreport import _stack_daily_dists
        out = _stack_daily_dists([
            {'n': 100, 'median_floor': 3, 'share_公寓': 0.2, 'rooftop_rate': 0.0},
            {'n': 300, 'median_floor': 5, 'share_公寓': 0.4, 'rooftop_rate': 0.02},
            {'n': 100, 'median_floor': 4, 'share_公寓': 0.2, 'rooftop_rate': 0.0}])
        self.assertEqual(out, {'n': 500, 'median_floor': 4, 'share_公寓': 0.32, 'rooftop_rate': 0.012})
        self.assertEqual(_stack_daily_dists([{'n': 0}]), {'n': 0})


if __name__ == '__main__':
    unittest.main()
