'''twrhctl localprune：EFS 舊分區清理（只刪 S3 上同 key 同大小的；日目錄全有全無）。'''
import os
from unittest import mock

from tests.helpers import TempEnvTestCase, run_command


class LocalPruneTests(TempEnvTestCase):

    target_date = '2026-10-15'

    def put(self, rel, data=b'x', base='artifacts'):
        path = os.path.join(self.tmp, base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
        return path

    def prune(self, s3, *argv, bucket='twrh-test'):
        with mock.patch.dict(os.environ, {'TWRH_RAW_BUCKET': bucket}), \
                mock.patch('twrhctl.commands.localprune.s3_size',
                           side_effect=lambda _b, key: s3.get(key)):
            return run_command('localprune', *argv)

    def test_old_verified_files_go_recent_and_unverified_stay(self):
        old_list = self.put('list/591/2026-10-01/run.jsonl.zst')
        new_list = self.put('list/591/2026-10-10/run.jsonl.zst')
        old_latest = self.put('latest/591/daily/2026-10-01.parquet')
        old_raw = self.put('591/2026-10-01.tar.zst', base='raws')
        old_index = self.put('591/2026-10-01.index.jsonl', base='raws')
        scratch = self.put('scratch/591/2026-10-01/a.html', base='raws')
        queue = self.put('queue/591/2026-10-01/detail/seeds/run.jsonl')
        s3 = {'list/591/2026-10-01/run.jsonl.zst': 1, 'list/591/2026-10-10/run.jsonl.zst': 1,
              'latest/591/daily/2026-10-01.parquet': 1,
              'raw/591/2026-10-01.tar.zst': 1, 'raw/591/2026-10-01.index.jsonl': 1}
        code, out, _ = self.prune(s3)
        self.assertFalse(code)
        for gone in (old_list, old_latest, old_raw, old_index):
            self.assertFalse(os.path.exists(gone), gone)
        self.assertFalse(os.path.exists(os.path.dirname(old_list)))
        for stays in (new_list, scratch, queue):
            self.assertTrue(os.path.exists(stays), stays)
        self.assertIn('removed 3 units', out)   # raw 日包＋index 是同一單位

    def test_day_dir_is_all_or_nothing(self):
        '''partition_files 本地有任一檔就不回 S3：刪一半＝讀取端少讀 run。'''
        a = self.put('parsed/591/2026-10-01/run.parquet')
        b = self.put('parsed/591/2026-10-01/sweep-1100.parquet')
        code, out, _ = self.prune({'parsed/591/2026-10-01/run.parquet': 1})
        self.assertFalse(code)
        self.assertTrue(os.path.exists(a) and os.path.exists(b))
        self.assertIn('KEEP parsed/591/2026-10-01', out)

    def test_size_mismatch_keeps(self):
        path = self.put('deals/591/2026-10-01/run.parquet', b'xyz')
        self.prune({'deals/591/2026-10-01/run.parquet': 1})
        self.assertTrue(os.path.exists(path))

    def test_snapshot_keeps_previous_month_for_export(self):
        '''export 只讀本地 snapshot、缺檔靜默跳過：上月 1 日起都要留。'''
        aug = self.put('snapshot/591/2026-08-31.parquet')
        sep = self.put('snapshot/591/2026-09-01.parquet')
        s3 = {'snapshot/591/2026-08-31.parquet': 1, 'snapshot/591/2026-09-01.parquet': 1}
        self.prune(s3)
        self.assertFalse(os.path.exists(aug))
        self.assertTrue(os.path.exists(sep))

    def test_no_bucket_deletes_nothing(self):
        path = self.put('list/591/2026-10-01/run.jsonl.zst')
        code, out, _ = self.prune({'list/591/2026-10-01/run.jsonl.zst': 1}, bucket='')
        self.assertFalse(code)
        self.assertTrue(os.path.exists(path))
        self.assertIn('nothing pruned', out)

    def test_dry_run(self):
        path = self.put('list/591/2026-10-01/run.jsonl.zst')
        code, out, _ = self.prune({'list/591/2026-10-01/run.jsonl.zst': 1}, '--dry-run')
        self.assertTrue(os.path.exists(path))
        self.assertIn('(dry-run): removed 1 units', out)
