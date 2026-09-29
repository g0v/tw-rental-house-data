'''rental/filequeue（純檔案 queue）：摺疊語意、attempts 跨檔累計、殘留／孤兒、位置輪分、key。'''
import unittest

from tests.helpers import TEST_DATE, TempEnvTestCase


class FileQueueTests(TempEnvTestCase):

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
        w1.close()
        w2.close()

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

    def test_make_key_is_content_based_and_run_scoped_on_request(self):
        from rental.filequeue import make_key
        self.assertEqual(make_key({'page': 0, 'id': 1, 'name': 'A'}), 'id=1|name=A|page=0')
        self.assertEqual(make_key({'id': 'h1'}, run='sweep-0501'), 'sweep-0501#id=h1')
        self.assertEqual(make_key('raw'), 'raw')


if __name__ == '__main__':
    unittest.main()
