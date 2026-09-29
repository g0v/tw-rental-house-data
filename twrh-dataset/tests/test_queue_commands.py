'''twrhctl 的 queue 指令：queuefinalize（seeds == terminals）、queuebusy（心跳互斥）、rawpack。'''
import io
import os
import subprocess
import time
import unittest
from datetime import date
from unittest import mock

from tests.helpers import (TEST_DATE, VENDOR_NAME, TempEnvTestCase, drain, make_queue,
                           make_response, run_command)


class QueueFinalizeTests(TempEnvTestCase):
    '''queuefinalize：seeds==terminals 斷言、零產出、dead 門檻、第三類型（deal）。'''

    def setUp(self):
        super().setUp()
        self._n = 0

    def add(self, type_name, status, n=1, error=None, attempts=1):
        '''n 顆種子；status=None＝從未認領（pending），其餘寫一行終結紀錄。'''
        from rental import filequeue as fq
        seeds = fq.SeedsWriter('591', TEST_DATE, type_name, 'run')
        term = fq.TerminalWriter('591', TEST_DATE, type_name, 'run', 'worker-t')
        for _ in range(n):
            self._n += 1
            key = 'k{}'.format(self._n)
            seeds.append(key, {'id': key})
            if status:
                term.append(key, status, attempts, error=error)
        seeds.close()
        term.close()

    def finalize(self):
        return run_command('queuefinalize', '--no-cleanup', '--no-slack')

    def assert_green(self):
        code, out, err = self.finalize()
        self.assertEqual(code, 0, out + err)
        self.assertIn('seeds == terminals', out)
        return out

    def assert_red(self, *fragments):
        code, out, err = self.finalize()
        self.assertEqual(code, 1, out + err)
        for fragment in fragments:
            self.assertIn(fragment, err)
        return out, err

    def test_green_when_all_terminal(self):
        self.add('list', 'done', 3)
        self.add('detail', 'done', 100)
        out = self.assert_green()
        self.assertIn('591 租屋網 detail: seeds 100 = done 100 + dead 0 + residue 0', out)

    def test_red_on_residue(self):
        self.add('list', 'done', 3)
        self.add('detail', 'done', 10)
        self.add('detail', 'failed', 2, error='http_403')
        self.add('detail', None, 1)
        self.assert_red('未收斂', 'http_403')

    def test_red_on_dead_ratio_over_threshold(self):
        '''403 全滅場景：全數 dead——形式上 seeds==done+dead，但必須紅。'''
        self.add('list', 'done', 3)
        self.add('detail', 'dead', 50, error='http_403', attempts=3)
        self.assert_red('dead 比率', 'http_403')

    def test_green_with_dead_below_threshold(self):
        self.add('list', 'done', 3)
        self.add('detail', 'done', 99)
        self.add('detail', 'dead', 1, error='http_500', attempts=3)
        out = self.assert_green()   # 1% < 5% 門檻：照列訊息、不當錯誤
        self.assertIn('http_500', out)

    def test_red_on_zero_seeds(self):
        '''seed 零產出場景：detail 連一顆種子都沒有。'''
        self.add('list', 'done', 3)
        self.assert_red('detail: 零種子')

    def test_deal_type_has_no_zero_seed_rule_but_must_converge(self):
        self.add('list', 'done', 2)
        self.add('detail', 'done', 50)
        self.assert_green()          # deals 沒種子的日子合法（stage 未排程）
        self.add('deal', 'done', 3)
        self.add('deal', 'failed', 1)
        _out, err = self.assert_red('deal')
        self.assertNotIn('deal: 零種子', err)

    def test_finalize_and_manifest_queue_stats_read_queue_files(self):
        from crawlerrequest.enums import RequestType
        from twrhctl import manifests
        q = make_queue()
        q.gen_persist_request({'id': 'a'})
        q.gen_persist_request({'id': 'b'})
        items = drain(q)
        list(q.parser_wrapper(make_response(items[0])))
        q.mark_failed(items[1], 'http_403')
        q.release_claims()
        stats = manifests._queue_stats(manifests._ts_of(date.fromisoformat(TEST_DATE)),
                                       RequestType.DETAIL, 'live')
        self.assertEqual((stats['seeds'], stats['done'], stats['dead'], stats['residue'], stats['source']),
                         (2, 1, 0, 1, 'file'))
        self.assertEqual(stats['errors'], {'http_403': 1})
        self.assertIsNone(manifests._queue_stats(None, RequestType.DETAIL, 'backfill'))
        _out, err = self.assert_red('list: 零種子')
        self.assertIn('detail: seeds 2 = done 1 + dead 0 + residue 1', _out)

    def test_green_for_list_and_detail_driven_through_queue(self):
        for is_list in (False, True):                             # 零種子規則管 list／detail 兩型
            q = make_queue(is_list=is_list)
            q.gen_persist_request({'id': 'a'} if not is_list else {'id': 1, 'name': 'A', 'page': 0})
            r = q.next_request()
            list(q.parser_wrapper(make_response(r.meta['db_request'])))
            q.release_claims()
        out = self.assert_green()
        self.assertIn('detail: seeds 1 = done 1 + dead 0 + residue 0', out)
        self.assertIn('list: seeds 1 = done 1 + dead 0 + residue 0', out)


class QueueBusyTests(TempEnvTestCase):
    '''flow sweep 的互斥：同 vendor 同日、窗內 touch 過的 worker 心跳才算忙。'''

    def busy(self, *args):
        code, out, err = run_command('queuebusy', '--vendor', VENDOR_NAME, *args)
        self.assertIn(code, (0, 1), out + err)
        return code

    def test_idle_when_queue_has_seeds_but_no_worker(self):
        from rental import filequeue as fq
        w = fq.SeedsWriter('591', TEST_DATE, 'detail', 'run')
        w.append('a', {'id': 'a'})
        w.close()
        self.assertEqual(self.busy(), 0)

    def test_heartbeat_lifecycle(self):
        self.assertEqual(self.busy(), 0)
        q = make_queue()                                           # 建立即 touch 心跳
        self.assertEqual(self.busy('--source', 'file'), 1)
        old = time.time() - 3 * 3600
        os.utime(q.heartbeat.path, (old, old))                     # SIGKILL 殘留：過窗即不算
        self.assertEqual(self.busy('--hours', '2'), 0)
        self.assertEqual(self.busy('--hours', '4'), 1)
        q.heartbeat.touch()
        self.assertEqual(self.busy(), 1)
        q.release_claims()                                         # 收工刪心跳
        self.assertEqual(self.busy(), 0)

    def test_other_vendor_and_other_day_do_not_block(self):
        from rental import filequeue as fq
        fq.Heartbeat('好房網', TEST_DATE, 'detail', 'run', 'w').touch()
        fq.Heartbeat('591', '2026-01-14', 'detail', 'run', 'w').touch()
        self.assertEqual(self.busy(), 0)
        self.assertEqual(self.busy('--date', '2026-01-14'), 1)

    def test_db_source_and_unknown_vendor_refused(self):
        self.assertEqual(run_command('queuebusy', '--vendor', VENDOR_NAME, '--source', 'db')[0], 1)
        self.assertEqual(run_command('queuebusy', '--vendor', 'nope')[0], 1)


class RawPackTests(TempEnvTestCase):
    '''rawpack：同日多次 run 聯集（sweep 上線後）、孤兒日期、vendor 目錄正規化、對帳只報量。'''

    def scratch(self, vendor_dir, date_str, house_id, html):
        day = os.path.join(self.tmp, 'raws', 'scratch', vendor_dir, date_str)
        os.makedirs(day, exist_ok=True)
        with open(os.path.join(day, '{}.detail.html'.format(house_id)), 'w') as f:
            f.write(html)

    def pack_path(self, date_str):
        return os.path.join(self.tmp, 'raws', '591', date_str + '.tar.zst')

    def members(self, date_str):
        out = subprocess.run(['tar', '-I', 'zstd', '-tf', self.pack_path(date_str)],
                             capture_output=True, text=True, check=True)
        return sorted(out.stdout.split())

    def member(self, date_str, name):
        return subprocess.run(['tar', '-I', 'zstd', '-xOf', self.pack_path(date_str), name],
                              capture_output=True, check=True).stdout

    def rawpack(self, *args):
        code, out, err = run_command('rawpack', '--date', TEST_DATE, '--keep-local', *args)
        self.assertEqual(code, 0, out + err)
        return out

    def test_cleanup_scratch_is_after_effect_not_the_job(self):
        '''刪 scratch 是善後：刪不掉只能留痕、不得拋例外，更不得擋掉上傳（2026-09-17）。'''
        from twrhctl.commands.rawpack import Command
        self.scratch('591', TEST_DATE, 'a', '<html>a</html>')
        day_dir = os.path.join(self.tmp, 'raws', 'scratch', '591', TEST_DATE)
        code, out, err = run_command('rawpack', '--date', TEST_DATE)
        self.assertEqual(code, 0, out + err)
        self.assertFalse(os.path.exists(day_dir))      # 整棵刪掉
        self.assertIn('a.detail.html', self.members(TEST_DATE))
        # 目錄已經不在了再刪一次：不得拋例外，但要留痕
        with mock.patch('sys.stdout', new_callable=io.StringIO) as stdout:
            Command().cleanup_scratch([day_dir], {'keep_scratch': False})
        self.assertIn('NOTE cleanup scratch 殘留', stdout.getvalue())

    def test_cleanup_failure_cannot_block_upload(self):
        '''正事（上傳日包）排在善後（刪 scratch）之前：就算 cleanup 整個炸掉，日包也已上傳。'''
        from twrhctl.commands.rawpack import Command
        self.scratch('591', TEST_DATE, 'a', '<html>a</html>')
        uploaded = []
        with mock.patch.dict(os.environ, {'TWRH_RAW_BUCKET': 'dummy'}), \
                mock.patch.object(Command, 'existing_pack', lambda self, v, d: None), \
                mock.patch.object(Command, 'upload',
                                  lambda self, b, v, p, i, k: uploaded.append(p)), \
                mock.patch.object(Command, 'cleanup_scratch', side_effect=OSError('boom')):
            with self.assertRaises(OSError):
                run_command('rawpack', '--date', TEST_DATE)
        self.assertEqual(len(uploaded), 1)   # cleanup 炸掉之前就上傳了

    def test_same_day_runs_union_and_orphan_dates(self):
        # 日跑：A、B
        self.scratch('591', TEST_DATE, 'A', '<a1>')
        self.scratch('591', TEST_DATE, 'B', '<b1>')
        self.rawpack()
        self.assertEqual(self.members(TEST_DATE), ['A.detail.html', 'B.detail.html'])
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
            os.path.join(self.tmp, 'raws', 'scratch', '591', '2026-01-14')))
        with open(os.path.join(self.tmp, 'raws', '591', TEST_DATE + '.index.jsonl')) as f:
            self.assertEqual(len(f.read().splitlines()), 3)

    def test_reconcile_reports_counts_only(self):
        '''DB 無 raw：--reconcile／--reconcile-only 只報量，內容不比、恆綠。'''
        self.scratch('591', TEST_DATE, 'A', '<a1>')
        self.assertIn('detail members 1 vs queue done 0', self.rawpack('--reconcile', '--full'))
        self.rawpack('--reconcile-only', '--full')
        self.scratch('591', TEST_DATE, 'A', '<a-changed>')
        self.rawpack('--reconcile')
        self.assertEqual(self.member(TEST_DATE, 'A.detail.html'), b'<a-changed>')

    def test_reconcile_counts_done_from_file_queue(self):
        from twrhctl.commands.rawpack import Command
        q = make_queue()
        q.gen_persist_request({'id': 'a'})
        q.gen_persist_request({'id': 'b'})
        r = q.next_request()
        list(q.parser_wrapper(make_response(r.meta['db_request'])))
        q.release_claims()
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            Command().reconcile('591', TEST_DATE, None, [{'member': 'x.detail.html'}], False)
        self.assertIn('detail members 1 vs queue done 1', out.getvalue())

    def test_no_scratch_is_a_noop(self):
        self.assertIn('nothing to pack', self.rawpack())


if __name__ == '__main__':
    unittest.main()
