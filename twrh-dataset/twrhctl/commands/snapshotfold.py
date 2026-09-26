'''snapshotfold（twrhctl 版，無 Django；由 django/rental/management/commands/snapshotfold.py 搬來，
只留檔案時代：DB 摺出的 --bootstrap／--backfill 與 house DB 回退拒跑）。

原說明：4c snapshot 分區。

    manage.py snapshotfold [--date D] [--vendor] [--no-upload] [--only final|provisional]
    manage.py snapshotfold --bootstrap --date D      # 只從 DB 摺出 D 這天（起點／#11 回填）
    manage.py snapshotfold --reupload --date D       # 只把本地 D 的檔補上 S3
    manage.py snapshotfold --backfill --from D1 --to D2 [--force]
        # #11 回填：D1..D2 每天由 HouseTS 摺出（carry 欄只留該日列推得出的，見 snapshot_db）；
        # 已存在（本地或 S3）的天數跳過，--force 才覆寫（S3 永不覆蓋原則：回填只補缺的天）

flow 每天做兩件事，**拆在兩個 stage**（`--only` 選一件；不給＝兩件都做，本機手跑用）：
1. 昨日 final ＝ fold(前日 snapshot, 昨日全部 list／parsed／deals 分區)——昨日的輸入
   此刻已齊（各輪 sweep 到 23:02 收工）。前日 snapshot 不存在（一階遞迴的起點）
   → 昨日改由 DB 摺出（rental/snapshot_db.bootstrap_rows），不再往前追。
   flow 的 `snapshotfinal` stage，**排在 seed 之前**（2026-09-19）：S1 的種子判準讀昨日
   snapshot 的 carry 欄，若 final 留到 seed 之後才摺，seed 讀到的永遠是昨日 04:1x 的
   provisional——昨日七輪 sweep 抓過 detail 的戶整列不在裡面、被當「從未 detail」重播
   （S1 首夜 9/19 實測多播 3,625 戶；provisional 與 final 差 3,929 戶、3,883 戶有昨日白天
   的 last_detail_at）。它只依賴昨日分區，搬到 seed 前沒有新的順序依賴。
2. 今日 provisional ＝ fold(昨日 final, 今日到目前的分區)——明天這一步會把它重摺
   成 final。同 key 覆寫是 snapshot 樹刻意的設計（bucket 有 versioning）。
   flow 的 `snapshot` stage（parsedcheck 之後）。

上傳失敗只印 `!!!`、本地檔保留（與 artifactpack 同：雙寫期 advisory）。
'''
import os
from datetime import date as date_cls, datetime, timedelta

from twrhctl.base import BaseCommand, CommandError

from rental import artifacts, snapshot
from rental.switches import house_db
from rental import vendors
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
        parser.add_argument('--only', choices=('final', 'provisional'),
                            help='只做其中一件：final＝昨日重摺（flow snapshotfinal stage，'
                                 'seed 之前）；provisional＝今日（flow snapshot stage）')
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
        vendor = vendors.get(options['vendor'], orm=False)
        short = vendor_dirname(vendor.name)
        bucket = None if options['no_upload'] else os.environ.get('TWRH_RAW_BUCKET')
        read_bucket = os.environ.get('TWRH_RAW_BUCKET')

        if options['backfill'] or options['bootstrap'] or house_db():
            # DB 已退場（S5）：從 DB 摺 snapshot 的兩條路（#11 回填、單日 bootstrap）與
            # house DB 回退都只剩 Django 版 manage.py snapshotfold 能跑
            raise CommandError('--backfill／--bootstrap／TWRH_HOUSE_DB=1 需要 DB，twrhctl 不支援')

        if options['reupload']:
            if not bucket:
                raise CommandError('--reupload 需要 TWRH_RAW_BUCKET')
            path = artifacts.snapshot_path(short, day.isoformat())
            if not os.path.exists(path):
                raise CommandError('no local snapshot for {}'.format(day))
            artifacts.upload_snapshot(bucket, short, day.isoformat(), path)
            return


        yesterday = day - timedelta(days=1)
        before = yesterday - timedelta(days=1)
        only = options['only']
        if only != 'provisional':
            if artifacts.snapshot_exists(short, before.isoformat(), read_bucket):
                self.fold(short, before, yesterday, 'final', read_bucket, bucket)
            elif artifacts.snapshot_exists(short, yesterday.isoformat(), read_bucket):
                print('=== snapshot {} {}: keep as is (no {} snapshot to refold from)'.format(
                    short, yesterday, before))
            else:
                self.replay_to(short, yesterday, read_bucket, bucket)
        if only != 'final':
            if not artifacts.snapshot_exists(short, yesterday.isoformat(), read_bucket):
                raise CommandError(
                    'snapshot {} missing — snapshotfinal stage 沒跑？'
                    '（--only provisional 需要昨日 final）'.format(yesterday))
            self.fold(short, yesterday, day, 'provisional', read_bucket, bucket)

    def replay_to(self, short, target, read_bucket, bucket):
        '''S3b：前日與昨日的 snapshot 都不在、又沒有 DB 可摺（flow 連兩晚沒走到 snapshot）。
        往回找最近一份 snapshot，從它的隔天逐日重放到 target——各日分區（list／parsed／deals）
        永遠留著，fold 是純函數，重放的結果與當時每天照跑相同。找不到任何一份＝冷啟動：
        以空的前日摺出 target（只有 target 當天的訊號，carry 欄從這天數起）。'''
        lookback = int(os.environ.get('TWRH_SNAPSHOT_REPLAY_DAYS', '14'))
        base = None
        for back in range(2, lookback + 1):
            d = target - timedelta(days=back)
            if artifacts.snapshot_exists(short, d.isoformat(), read_bucket):
                base = d
                break
        if base is None:
            print('!!! snapshot {} {}: no snapshot within {} days — cold start from empty'.format(
                short, target, lookback))
            self.fold(short, target - timedelta(days=1), target, 'final', read_bucket, bucket,
                      allow_empty_prev=True)
            return
        print('=== snapshot {} {}: replay from {} ({} days)'.format(
            short, target, base, (target - base).days))
        d = base + timedelta(days=1)
        while d <= target:
            self.fold(short, d - timedelta(days=1), d, 'final', read_bucket, bucket)
            d += timedelta(days=1)

    def fold(self, short, prev_day, day, kind, read_bucket, bucket, allow_empty_prev=False):
        prev_rows = artifacts.read_snapshot(short, prev_day.isoformat(), read_bucket)
        if prev_rows is None and allow_empty_prev:
            prev_rows = []
        if prev_rows is None:
            raise CommandError('snapshot {} missing, cannot fold {}'.format(prev_day, day))
        date_str = day.isoformat()
        stubs = list(artifacts.read_list_stubs(short, date_str, read_bucket))
        parsed = artifacts.read_parsed_rows(short, date_str, read_bucket)
        deals = artifacts.read_deal_events(short, date_str, read_bucket)
        n_prev, n_stubs, n_parsed, n_deals = len(prev_rows), len(stubs), len(parsed), len(deals)
        # 昨日 snapshot 沒有、今日又有訊號的戶（關閉多日後才進成交列表；掉出後回列）：
        # 先查 S3c 總表 latest(prev_day) 拿最後已知列（2026-09-19 起）；總表不在（起點／
        # 回填）才退回掃 deal lookback 天的 snapshot、且只為成交事件的戶（舊行為）
        prev_ids = {r['vendor_house_id'] for r in prev_rows}
        orphans = ({s['vendor_house_id'] for s in stubs} | {p['vendor_house_id'] for p in parsed}
                   | {e['vendor_house_id'] for e in deals}) - prev_ids
        closed_rows = artifacts.read_latest_rows_for(short, prev_day.isoformat(), orphans, read_bucket)
        recovered_from = 'latest'
        if closed_rows is None:
            recovered_from = 'earlier snapshots'
            orphans = {e['vendor_house_id'] for e in deals} - prev_ids
            lookback = int(os.environ.get('TWRH_DEAL_LOOKBACK_DAYS', '7'))   # 同 vendor profile 預設
            closed_rows = artifacts.find_closed_rows(short, orphans, prev_day.isoformat(), lookback, read_bucket)
        n_orphans, n_closed = len(orphans), len(closed_rows)
        rows = snapshot.fold(prev_rows, stubs, parsed, deals, date_str, vendor=short,
                             closed_rows=closed_rows)
        del closed_rows
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
        if n_orphans:
            print('    houses with signals today but not in {} snapshot: {} (recovered from {}: {}, '
                  'blank rows: {})'.format(prev_day, n_orphans, recovered_from, n_closed, n_orphans - n_closed))
        self.upload(bucket, short, day, path)

    def upload(self, bucket, short, day, path):
        if not bucket:
            return
        try:
            artifacts.upload_snapshot(bucket, short, day.isoformat(), path)
        except Exception as err:  # noqa: BLE001
            print('!!! snapshot upload failed for {} (local kept; snapshotfold --reupload): {}'.format(
                day, err))
