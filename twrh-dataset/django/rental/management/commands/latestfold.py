'''latestfold：S3c 全戶最新狀態總表（rental/latest.py）。

    manage.py latestfold [--date D] [--vendor] [--no-upload]
        # 總表(D−1) ＝ fold(總表(D−2), final snapshot(D−1))。flow 的 latest stage：排在
        # snapshotfinal（昨日 final 已摺好）之後、seed 之前；今日 provisional 的 fold 對
        # 「昨日 snapshot 沒有、今日又有訊號」的戶改查它（回列戶不再整列空白）。
        # 總表(D−2) 不存在 → 從 TWRH_LATEST_BOOTSTRAP_FROM（預設 2026-09-10，snapshot 譜系
        # 起點）逐日由 snapshot 重放到 D−1。
    manage.py latestfold --bootstrap --from D1 --to D2 [--no-upload]
        # 顯式重放：起點＝D1 的 snapshot 本身，逐日 fold 到 D2，只寫 D2

每月 1 日那份另存 monthly/<YYYY-MM>.parquet 當永久檢查點；daily/ 掛 14 天 lifecycle。
上傳失敗只印 `!!!`、本地檔保留（advisory，與 snapshotfold 同）。
'''
import os
from datetime import date as date_cls, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError

from rental import artifacts, latest
from rental.models import Vendor
from rental.raws import vendor_dirname
from rental import vendors

_SNAPSHOT_COLUMNS = [name for name, _ in latest.LATEST_FIELDS]


class Command(BaseCommand):
    help = 'Fold yesterday final snapshot into the all-houses latest-state table (S3c)'

    def add_arguments(self, parser):
        parser.add_argument('--date')
        parser.add_argument('--vendor', default='591 租屋網')
        parser.add_argument('--no-upload', action='store_true')
        parser.add_argument('--bootstrap', action='store_true')
        parser.add_argument('--from', dest='from_date')
        parser.add_argument('--to', dest='to_date')

    def handle(self, *_args, **options):
        vendor = vendors.get(options['vendor'])
        short = vendor_dirname(vendor.name)
        bucket = None if options['no_upload'] else os.environ.get('TWRH_RAW_BUCKET')
        read_bucket = os.environ.get('TWRH_RAW_BUCKET')

        if options['bootstrap']:
            start, end = self._parse(options['from_date']), self._parse(options['to_date'])
            if start is None or end is None or end < start:
                raise CommandError('--bootstrap 需要 --from/--to YYYY-MM-DD（from ≤ to）')
            self.replay(short, start, end, read_bucket, bucket)
            return

        day = self._parse(options['date'])
        if day is None:
            env = os.environ.get('TWRH_TARGET_DATE')
            day = datetime.strptime(env, '%Y-%m-%d').date() if env else date_cls.today()
        target = day - timedelta(days=1)
        prev = target - timedelta(days=1)
        prev_rows = artifacts.read_latest(short, prev.isoformat(), read_bucket)
        if prev_rows is None:
            start = self._parse(os.environ.get('TWRH_LATEST_BOOTSTRAP_FROM', '2026-09-10'))
            print('=== latest {} {}: no latest({}) — bootstrap by replaying snapshots {}..{}'.format(
                short, target, prev, start, target))
            self.replay(short, start, target, read_bucket, bucket)
            return
        self.fold_one(short, prev_rows, target, read_bucket, bucket)

    def replay(self, short, start, end, read_bucket, bucket):
        table = []
        day = start
        while day <= end:
            rows = artifacts.read_snapshot(short, day.isoformat(), read_bucket, columns=_SNAPSHOT_COLUMNS)
            if rows is None:
                raise CommandError('snapshot {} missing, cannot replay latest table'.format(day))
            table = latest.fold(table, rows)
            n_snap = len(rows)
            del rows
            print('    latest({}) = fold(prev, snapshot {} rows) -> {} rows'.format(day, n_snap, len(table)))
            day += timedelta(days=1)
        self.write(short, table, end, bucket)

    def fold_one(self, short, prev_rows, target, read_bucket, bucket):
        rows = artifacts.read_snapshot(short, target.isoformat(), read_bucket, columns=_SNAPSHOT_COLUMNS)
        if rows is None:
            raise CommandError('snapshot {} missing — snapshotfinal stage 沒跑？'.format(target))
        n_prev, n_snap = len(prev_rows), len(rows)
        table = latest.fold(prev_rows, rows)
        del prev_rows, rows
        print('=== latest {} {}: prev {} + snapshot {} -> {} rows'.format(
            short, target, n_prev, n_snap, len(table)))
        self.write(short, table, target, bucket)

    def write(self, short, table, day, bucket):
        by = {}
        for r in table:
            by[r['deal_status']] = by.get(r['deal_status'], 0) + 1
        path, n = artifacts.write_latest(table, short, day.isoformat())
        del table
        print('=== latest {} {}: {} rows deal_status {} -> {} ({:.1f} MB)'.format(
            short, day, n, by, path, os.path.getsize(path) / 1e6))
        if bucket:
            try:
                artifacts.upload_latest(bucket, short, day.isoformat(), path, monthly=(day.day == 1))
            except Exception as err:  # noqa: BLE001 — advisory：本地檔在，下次 --reupload 或重跑
                print('!!! latest upload failed: {}'.format(err))

    @staticmethod
    def _parse(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            raise CommandError('日期需為 YYYY-MM-DD：{}'.format(value))
