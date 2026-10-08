'''flow.py（stage 表、sweep 多 worker、log 即時 ship）、vendor profile、tools/compare_export、
「整條生產路徑不載入 django」與檔案時代 stage 指令冒煙。'''
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests.helpers import (ROOT_DIR, TEST_DATE, VENDOR_NAME, TempEnvTestCase, check_command,
                           snapshot_row)


class VendorProfileTests(unittest.TestCase):
    '''vendor profile 是資料、env 可覆寫；flow 依它組 stage。'''

    def test_profile_values_and_env_override(self):
        from crawler import vendor_profiles
        p = vendor_profiles.get('591')
        self.assertEqual(p.name, VENDOR_NAME)
        self.assertEqual(p.list_spider, 'list591')
        self.assertTrue(p.has_deals_stage)
        self.assertTrue(p.supports_frontier)
        with mock.patch.dict(os.environ, {'TWRH_SWEEP_PAGES': '', 'TWRH_DEAL_LOOKBACK_DAYS': ''}):
            self.assertEqual(p.frontier_pages, '30')
        with mock.patch.dict(os.environ, {'TWRH_SWEEP_PAGES': '12', 'TWRH_DEAL_LOOKBACK_DAYS': '9'}):
            self.assertEqual(p.frontier_pages, '12')
            self.assertEqual(p.deal_lookback_days, '9')
        self.assertEqual(vendor_profiles.names(), ['591'])
        with self.assertRaises(KeyError):
            vendor_profiles.get('nope')
        with self.assertRaises(AttributeError):
            p.no_such_key


class FlowStageTests(unittest.TestCase):
    '''stage 表順序與 dry-run 指令（scrapy 以外一律 python -m twrhctl）。'''

    class Opts:
        date = '2026-09-14'
        vendor = '591'

    def dry(self, body, ctx=None, env=None):
        import flow
        with mock.patch.dict(os.environ, env or {}, clear=False), \
                mock.patch.object(flow, 'DRY_RUN', True):
            buf = io.StringIO()
            with redirect_stdout(buf):
                body(ctx)
        return buf.getvalue(), [line for line in buf.getvalue().splitlines() if line.startswith('+ ')]

    def sweep_newdetail(self, env):
        import flow
        with mock.patch.dict(os.environ, env, clear=False):
            ctx = flow.Ctx(self.Opts, 'sweep')
            return self.dry(flow.stage_newdetail, ctx)[1]

    def test_cloud_sweep_multi_worker_sequence(self):
        cmds = self.sweep_newdetail({'TWRH_CLUSTER': 'twrh', 'TWRH_SWEEP_WORKERS': '2'})
        self.assertIn('seed_mode=new -a seed_only=True', cmds[0])
        self.assertIn('devop/workers.py launch', cmds[1])
        self.assertIn('consume_only=True', cmds[2])
        self.assertIn('consume_only=True', cmds[-1])   # mop-up
        self.assertEqual(len(cmds), 4)

    def test_local_or_zero_workers_keeps_two_passes(self):
        for env in ({'TWRH_CLUSTER': '', 'TWRH_SWEEP_WORKERS': '2'},
                    {'TWRH_CLUSTER': 'twrh', 'TWRH_SWEEP_WORKERS': '0'}):
            cmds = self.sweep_newdetail(env)
            self.assertEqual(len(cmds), 2, env)
            self.assertTrue(all('seed_mode=new' in c and 'seed_only' not in c for c in cmds), env)

    def test_run_stages_fold_yesterday_final_before_seed(self):
        # S1 首夜（2026-09-19）：seed 讀昨日 snapshot 的 carry 欄；昨日 final 若在 seed 之後才摺，
        # seed 讀到的永遠是 provisional（多播 3,625 戶）。順序是這個缺陷的全部
        import flow
        names = flow.RUN_STAGE_NAMES
        self.assertLess(names.index('liststubs'), names.index('snapshotfinal'))
        self.assertLess(names.index('snapshotfinal'), names.index('latest'))
        self.assertLess(names.index('latest'), names.index('seed'))
        self.assertLess(names.index('queuefinalize'), names.index('rawpack'))
        # 1 日月包：緊接 snapshotfinal／latest、爬取之前（2026-10-01）——flow 中途被擋也有月包
        self.assertLess(names.index('latest'), names.index('export'))
        self.assertLess(names.index('export'), names.index('seed'))
        self.assertLess(names.index('snapshot'), names.index('manifest'))
        out = {name: self.dry(body)[1] for name, body in (
            ('snapshotfinal', flow.stage_snapshotfinal), ('latest', flow.stage_latest),
            ('snapshot', flow.stage_snapshot), ('export', flow.stage_export),
            ('queuefinalize', flow.stage_queuefinalize), ('manifest', flow.stage_manifest))}
        self.assertEqual(len(out['snapshotfinal']), 1)
        self.assertIn('-m twrhctl snapshotfold --only final', out['snapshotfinal'][0])
        self.assertIn('-m twrhctl snapshotfold --only provisional', out['snapshot'][0])
        self.assertIn('-m twrhctl latestfold', out['latest'][0])
        self.assertIn('-m twrhctl export -p --source snapshot', out['export'][0])
        self.assertIn('-m twrhctl queuefinalize', out['queuefinalize'][0])
        for cmds in out.values():
            self.assertTrue(all('manage.py' not in c for c in cmds))

    def test_export_on_first_refuses_without_final_snapshot(self):
        # snapshotfinal 是 advisory：失敗時磁碟上上月最後一天是 provisional，1 日月包寧可不出
        import io
        import tempfile
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        import flow
        calls = []
        ok = SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(flow, 'manage', side_effect=lambda *a, **k: calls.append(a) or ok):
            ctx = SimpleNamespace(date='2026-10-01', state_dir=os.path.join(tmp, 'st'))
            buf = io.StringIO()
            with redirect_stdout(buf):
                flow.stage_export(ctx)                    # 沒有 final 標記
            self.assertIn('!!! export skipped', buf.getvalue())
            self.assertEqual(calls, [])
            flow.stage_snapshotfinal(ctx)                 # 成功 → 留標記
            self.assertTrue(os.path.exists(flow.snapshotfinal_marker(ctx)))
            flow.stage_export(ctx)
            self.assertEqual(calls[-1], ('export', '-p', '--source', 'snapshot'))
            # 再跑一次 snapshotfinal 失敗 → 標記清掉、export 又拒跑
            fail = SimpleNamespace(returncode=1)
            with mock.patch.object(flow, 'manage', return_value=fail), redirect_stdout(io.StringIO()):
                flow.stage_snapshotfinal(ctx)
            self.assertFalse(os.path.exists(flow.snapshotfinal_marker(ctx)))
            n = len(calls)
            with redirect_stdout(io.StringIO()):
                flow.stage_export(ctx)
            self.assertEqual(len(calls), n)
            # 非 1 日：export -p 自判不出貨，照常呼叫、不看標記
            flow.stage_export(SimpleNamespace(date='2026-10-02', state_dir=ctx.state_dir))
            self.assertEqual(calls[-1], ('export', '-p', '--source', 'snapshot'))

    def test_prune_runs_last_in_daily_run_only(self):
        # EFS 清理（2026-10-08）：前面的 stage 都可能讀前幾天的本地檔；sweep 不清
        import flow
        names = flow.RUN_STAGE_NAMES
        self.assertEqual(names[-2:], ['prune', 'logs'])
        self.assertNotIn('prune', flow.SWEEP_STAGE_NAMES)
        self.assertIn('-m twrhctl localprune', self.dry(flow.stage_prune)[1][0])

    def test_db_era_stages_are_gone(self):
        import flow
        for gone in ('seedcheck', 'parsedcheck', 'synthts', 'sync', 'snapshotcheck',
                     'exportcheck', 'filequeuecheck', 'nodjango'):
            self.assertNotIn(gone, flow.RUN_STAGE_NAMES)
            self.assertNotIn(gone, flow.SWEEP_STAGE_NAMES)
        self.assertEqual(flow.SWEEP_STAGE_NAMES[:2], ['busy', 'frontier'])

    def test_sweep_busy_yields(self):
        import flow
        ctx = flow.Ctx(self.Opts, 'sweep')
        self.assertTrue(ctx.run_id.startswith('sweep-'))
        with mock.patch.object(flow, 'manage', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(flow.SweepYield):
                flow.stage_busy(ctx)

    def test_seed_mode_flags(self):
        import flow
        with mock.patch.dict(os.environ, {'TWRH_DETAIL_SEED_MODE': 'diff',
                                          'TWRH_DETAIL_REFRESH_JITTER': '2'}):
            ctx = flow.Ctx(self.Opts)
        self.assertEqual(ctx.seed_mode_flags(), ['-a', 'seed_mode=diff', '-a', 'refresh_days=7',
                                                 '-a', 'refresh_jitter=2'])


class ScrapyLogShipTests(unittest.TestCase):
    '''spider log 歸檔完立刻 gzip＋上 S3（2026-09-19）：讀完（breaker）才 ship，且 ship 在 raise 之前。'''

    def run_stage_list(self, env, log_text):
        import flow
        tmp = tempfile.mkdtemp(prefix='twrh-logship-')
        self.addCleanup(__import__('shutil').rmtree, tmp, True)
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(' '.join(cmd))
            return subprocess.CompletedProcess(cmd, 0, '', '')

        class Opts:
            date = '2026-09-19'
            vendor = '591'
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(flow, 'DRY_RUN', False), \
                mock.patch.object(flow, 'BASE', tmp), \
                mock.patch.object(flow, 'LOGS_DIR', os.path.join(tmp, 'logs')), \
                mock.patch.object(flow, 'run', fake_run):
            ctx = flow.Ctx(Opts, 'run')
            with open(os.path.join(tmp, 'scrapy.log'), 'w') as f:
                f.write(log_text)
            err = None
            try:
                flow.stage_list(ctx)
            except flow.StageFailed as e:
                err = e
        logs = os.path.join(tmp, 'logs')
        return calls, err, sorted(os.listdir(logs)) if os.path.isdir(logs) else [], ctx.stamp

    def test_ships_gz_immediately_and_before_raising(self):
        calls, err, files, stamp = self.run_stage_list(
            {'TWRH_CLUSTER': 'twrh'}, 'INFO: crawled\nERROR: error_rate_exceeded\n')
        self.assertIsNotNone(err)                       # breaker 仍然 raise
        self.assertEqual(files, ['{}.list.log.gz'.format(stamp)])
        self.assertEqual(len(calls), 2)
        self.assertIn('scrapy crawl list591', calls[0])
        self.assertIn('ship_logs', calls[1])
        self.assertTrue(calls[1].endswith('{}.list.log'.format(stamp)))

    def test_local_only_gzips(self):
        calls, err, files, stamp = self.run_stage_list({'TWRH_CLUSTER': ''}, 'INFO: fine\n')
        self.assertIsNone(err)
        self.assertEqual(files, ['{}.list.log.gz'.format(stamp)])
        self.assertEqual(len(calls), 1)                 # 沒有 ship_logs


class CompareExportTests(unittest.TestCase):
    '''tools/compare_export.py：逐 byte 之外的小數位對映、殘餘戶數門檻。'''

    HEADER = '物件編號,坪數,每坪租金（含管理費與停車費）,房數\n'

    def compare(self, left_rows, right_rows, *flags):
        with tempfile.TemporaryDirectory(prefix='twrh-cmpexport-') as tmp:
            paths = []
            for name, rows in (('db', left_rows), ('snap', right_rows)):
                p = os.path.join(tmp, name + '.csv')
                with open(p, 'w') as f:
                    f.write(self.HEADER + ''.join(r + '\n' for r in rows))
                paths.append(p)
            tool = os.path.join(ROOT_DIR, 'tools', 'compare_export.py')
            proc = subprocess.run([sys.executable, tool, *paths, *flags], capture_output=True, text=True)
        return proc.returncode, proc.stdout

    def test_decimal_mapping_is_identical_only_with_expect_mapped(self):
        db = ['2,22.6,1106.19,2', '1,10,1000,1', '3,19.0,1000,1']
        snap = ['1,10,1000,1', '2,22.58,1107.17,2', '3,18.95,1000,1']
        code, out = self.compare(db, snap, '--expect-mapped')
        self.assertEqual(code, 0, out)
        self.assertIn('小數位對映', out)
        self.assertIn('坪數 2 戶', out)
        self.assertIn('每坪租金（含管理費與停車費） 1 戶', out)
        code, out = self.compare(db, snap)             # 純逐 byte：仍是 DIFF
        self.assertEqual(code, 1, out)

    def test_max_residual_threshold(self):
        db = ['1,10,1000,1', '2,5.0,2000,1', '4,8,1000,2']
        snap = ['1,10,1000,1', '2,5.4,2000,3']
        code, out = self.compare(db, snap, '--expect-mapped', '--max-residual', '2')
        self.assertEqual(code, 0, out)
        self.assertIn('WITHIN — 殘餘 2 戶', out)
        code, out = self.compare(db, snap, '--expect-mapped', '--max-residual', '1')
        self.assertEqual(code, 1, out)
        self.assertIn('DIFF — 殘餘 2 戶', out)

    def test_real_difference_still_diff(self):
        code, out = self.compare(['1,10,1000,1', '2,5.0,2000,1'], ['1,10,1000,1', '2,5.4,2000,1'],
                                 '--expect-mapped')
        self.assertEqual(code, 1, out)
        self.assertIn('坪數', out)


class NoDjangoTests(unittest.TestCase):
    '''S6：爬蟲、pipeline、flow 與每支 twrhctl 指令在同一行程 import，django 不得出現。
    （venv 仍裝著 Django；twrh-dataset/django/ 又有 __init__.py——誰 import 都會現形。）'''

    def test_production_modules_import_without_django(self):
        commands = sorted(f[:-3] for f in os.listdir(os.path.join(ROOT_DIR, 'twrhctl', 'commands'))
                          if f.endswith('.py') and not f.startswith('_'))
        self.assertIn('queuefinalize', commands)
        modules = ['crawler.general_settings', 'crawler.extensions.sentry', 'crawler.pipelines',
                   'crawler.spiders.persist_queue', 'crawler.spiders.list591_spider',
                   'crawler.spiders.detail591_spider', 'crawler.spiders.deal591_spider',
                   'flow', 'twrhctl', 'twrhctl.manifests',
                   'rental.filequeue', 'rental.artifacts', 'rental.snapshot', 'rental.latest',
                   'rental.seeding', 'rental.known', 'crawlerrequest.quality'] + \
            ['twrhctl.commands.' + c for c in commands]
        code = ('import importlib, sys\n'
                'import tests\n'
                'for name in sys.argv[1:]:\n'
                '    importlib.import_module(name)\n'
                'import crawler\n'
                'print(crawler.__file__)\n'
                'leaked = sorted(m for m in sys.modules if m == "django" or m.startswith("django."))\n'
                'print(leaked[:5])\n'
                'sys.exit(1 if leaked else 0)\n')
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'SENTRY_DSN')}
        proc = subprocess.run([sys.executable, '-c', code, *modules], cwd=ROOT_DIR,
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        # 跑的是本 checkout 的碼（venv 的 .pth 另指主 checkout）
        self.assertEqual(proc.stdout.splitlines()[0],
                         os.path.join(ROOT_DIR, 'crawler', '__init__.py'))

    def test_tests_import_worktree_code(self):
        import crawler
        import rental
        import twrhctl
        for mod in (crawler, rental, twrhctl):
            self.assertTrue(os.path.realpath(mod.__file__).startswith(ROOT_DIR + os.sep), mod.__file__)


class StageCommandsSmokeTests(TempEnvTestCase):
    '''日跑檔案 stage 的指令串（queuebusy→snapshotfold→latestfold→manifest→export）只靠檔案就跑得完。'''

    def test_stage_commands_run_on_files_only(self):
        from rental import artifacts
        artifacts.write_snapshot([snapshot_row('h1', '2026-01-14', deal_status=0, source='detail',
                                               monthly_price=9000, top_region=1)], '591', '2026-01-14')
        with mock.patch.dict(os.environ, {'TWRH_LATEST_BOOTSTRAP_FROM': '2026-01-14'}):
            check_command(self, 'queuebusy', '--vendor', VENDOR_NAME)
            check_command(self, 'snapshotfold', '--date', TEST_DATE, '--only', 'provisional', '--no-upload')
            check_command(self, 'latestfold', '--date', TEST_DATE, '--no-upload')
            check_command(self, 'manifest', '--no-upload')
            out_base = os.path.join(self.tmp, 'export', 'rental_house')
            os.makedirs(os.path.dirname(out_base))
            check_command(self, 'export', '-f', '20260114', '-t', '20260115', '--source', 'snapshot',
                          '-o', out_base)
        self.assertTrue(artifacts.snapshot_exists('591', TEST_DATE))
        self.assertTrue(artifacts.latest_exists('591', '2026-01-14'))
        exported = os.listdir(os.path.dirname(out_base))
        self.assertTrue(exported, 'export wrote nothing')


if __name__ == '__main__':
    unittest.main()
