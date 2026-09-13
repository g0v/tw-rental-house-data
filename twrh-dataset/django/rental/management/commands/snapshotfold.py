'''snapshotfold：4c snapshot 分區（雙寫期，DB 仍是真相）。

    manage.py snapshotfold [--date D] [--vendor] [--no-upload]
    manage.py snapshotfold --bootstrap --date D      # 只從 DB 摺出 D 這天（起點／#11 回填）
    manage.py snapshotfold --reupload --date D       # 只把本地 D 的檔補上 S3
    manage.py snapshotfold --backfill --from D1 --to D2 [--force]
        # #11 回填：D1..D2 每天由 HouseTS 摺出（carry 欄只留該日列推得出的，見 snapshot_db）；
        # 已存在（本地或 S3）的天數跳過，--force 才覆寫（S3 永不覆蓋原則：回填只補缺的天）

flow 的 snapshot stage（parsedcheck 之後）每天做兩件事：
1. 昨日 final ＝ fold(前日 snapshot, 昨日全部 list／parsed／deals 分區)——昨日的輸入
   此刻已齊（各輪 sweep 到 23:02 收工）。前日 snapshot 不存在（一階遞迴的起點）
   → 昨日改由 DB 摺出（rental/snapshot_db.bootstrap_rows），不再往前追。
2. 今日 provisional ＝ fold(昨日 final, 今日到目前的分區)——明天這一步會把它重摺
   成 final。同 key 覆寫是 snapshot 樹刻意的設計（bucket 有 versioning）。

上傳失敗只印 `!!!`、本地檔保留（與 artifactpack 同：雙寫期 advisory）。
'''
import os
from datetime import date as date_cls, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError

from rental import artifacts, snapshot, snapshot_db
from rental.models import Vendor
from rental.raws import vendor_dirname


class Command(BaseCommand):
    help = 'Fold yesterday (final) and today (provisional) snapshot parquet from partitions'

    def add_arguments(self, parser):
        parser.add_argument('--date')
        parser.add_argument('--vendor', default='591 租屋網')
        parser.add_argument('--no-upload', action='store_true')
        parser.add_argument('--bootstrap', action='store_true',
                            help='只從 DB 摺出 --date 這一天（覆寫既有檔）')
        parser.add_argument('--reupload', action='store_true')
        parser.add_argument('--backfill', action='store_true',
                            help='#11：--from..--to 每天由 HouseTS 摺出（過去日、無 House carry）')
        parser.add_argument('--from', dest='from_date')
        parser.add_argument('--to', dest='to_date')
        parser.add_argument('--force', action='store_true',
                            help='--backfill 時覆寫已存在的天')

    def handle(self, *_args, **options):
        if options['date']:
            try:
                day = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('--date 需為 YYYY-MM-DD')
        else:
            env = os.environ.get('TWRH_TARGET_DATE')
            day = datetime.strptime(env, '%Y-%m-%d').date() if env else date_cls.today()
        vendor = Vendor.objects.get(name=options['vendor'])
        short = vendor_dirname(vendor.name)
        bucket = None if options['no_upload'] else os.environ.get('TWRH_RAW_BUCKET')
        read_bucket = os.environ.get('TWRH_RAW_BUCKET')

        if options['backfill']:
            self.backfill(vendor, short, options, read_bucket, bucket)
            return

        if options['reupload']:
            if not bucket:
                raise CommandError('--reupload 需要 TWRH_RAW_BUCKET')
            path = artifacts.snapshot_path(short, day.isoformat())
            if not os.path.exists(path):
                raise CommandError('no local snapshot for {}'.format(day))
            artifacts.upload_snapshot(bucket, short, day.isoformat(), path)
            return

        if options['bootstrap']:
            self.bootstrap(vendor, short, day, bucket)
            return

        yesterday = day - timedelta(days=1)
        before = yesterday - timedelta(days=1)
        if artifacts.snapshot_exists(short, before.isoformat(), read_bucket):
            self.fold(short, before, yesterday, 'final', read_bucket, bucket)
        elif artifacts.snapshot_exists(short, yesterday.isoformat(), read_bucket):
            print('=== snapshot {} {}: keep as is (no {} snapshot to refold from)'.format(
                short, yesterday, before))
        else:
            print('=== snapshot {} {}: no {} snapshot — bootstrap from DB'.format(
                short, yesterday, before))
            self.bootstrap(vendor, short, yesterday, bucket)
        self.fold(short, yesterday, day, 'provisional', read_bucket, bucket)

    def backfill(self, vendor, short, options, read_bucket, bucket):
        try:
            start = datetime.strptime(options['from_date'] or '', '%Y-%m-%d').date()
            end = datetime.strptime(options['to_date'] or '', '%Y-%m-%d').date()
        except ValueError:
            raise CommandError('--backfill 需要 --from/--to YYYY-MM-DD')
        if end < start:
            raise CommandError('--to 早於 --from')
        day = start
        while day <= end:
            date_str = day.isoformat()
            if not options['force'] and artifacts.snapshot_exists(short, date_str, read_bucket):
                print('=== snapshot {} {} backfill: exists, skip (--force to overwrite)'.format(
                    short, date_str))
            else:
                rows = snapshot_db.bootstrap_rows(vendor, day, carry='ts')
                by_source = {}
                for r in rows:
                    by_source[r['source']] = by_source.get(r['source'], 0) + 1
                path, n = artifacts.write_snapshot(rows, short, date_str)
                del rows
                print('=== snapshot {} {} backfill (from HouseTS): {} rows {} -> {} ({:.1f} MB)'.format(
                    short, date_str, n, by_source, path, os.path.getsize(path) / 1e6))
                self.upload(bucket, short, day, path)
            day += timedelta(days=1)

    def bootstrap(self, vendor, short, day, bucket):
        rows = snapshot_db.bootstrap_rows(vendor, day)
        path, n = artifacts.write_snapshot(rows, short, day.isoformat())
        print('=== snapshot {} {} bootstrap (from DB): {} rows -> {} ({:.1f} MB)'.format(
            short, day, n, path, os.path.getsize(path) / 1e6))
        self.upload(bucket, short, day, path)

    def fold(self, short, prev_day, day, kind, read_bucket, bucket):
        prev_rows = artifacts.read_snapshot(short, prev_day.isoformat(), read_bucket)
        if prev_rows is None:
            raise CommandError('snapshot {} missing, cannot fold {}'.format(prev_day, day))
        date_str = day.isoformat()
        stubs = list(artifacts.read_list_stubs(short, date_str, read_bucket))
        parsed = artifacts.read_parsed_rows(short, date_str, read_bucket)
        deals = artifacts.read_deal_events(short, date_str, read_bucket)
        n_prev, n_stubs, n_parsed, n_deals = len(prev_rows), len(stubs), len(parsed), len(deals)
        rows = snapshot.fold(prev_rows, stubs, parsed, deals, date_str, vendor=short)
        del prev_rows, stubs, parsed, deals   # fold 已 pop 掉昨日列；放掉輸入，寫檔前騰記憶體
        by_source = {}
        for r in rows:
            by_source[r['source']] = by_source.get(r['source'], 0) + 1
        path, n = artifacts.write_snapshot(rows, short, date_str)
        del rows
        print('=== snapshot {} {} {}: prev {} + stubs {} + parsed {} + deals {} -> {} rows '
              '{} -> {} ({:.1f} MB)'.format(
                  short, day, kind, n_prev, n_stubs, n_parsed, n_deals,
                  n, by_source, path, os.path.getsize(path) / 1e6))
        self.upload(bucket, short, day, path)

    def upload(self, bucket, short, day, path):
        if not bucket:
            return
        try:
            artifacts.upload_snapshot(bucket, short, day.isoformat(), path)
        except Exception as err:  # noqa: BLE001
            print('!!! snapshot upload failed for {} (local kept; snapshotfold --reupload): {}'.format(
                day, err))
