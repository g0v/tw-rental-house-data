'''snapshotcarryfill：把 snapshot 日檔裡 NULL 的 carry 欄從 House／HouseEtc 補齊。

**為什麼需要**（2026-09-17 查出來的）：fold 對「已關閉且今日無訊號」的戶不再攜帶，
而 deal591 的成交列表會連續數日重列同一戶（lookback 7 天）——於是早已掉出 snapshot
的戶被 `closed_rows` 復活分支撿回來，而撿回來的來源常是 **#11 回填的「無 carry 欄
歷史列」**（2026-09-10 拍板：過去日只填該日列推得出的 carry）。結果：復活列的
`last_seen_at`／`last_detail_at`／`last_fingerprint` 永久 NULL，`days_absent` 從復活日
重新數（DB 從真實 last_seen 數，所以兩邊差 1–2 天）。9/17 實測 17 戶（會隨天數成長）。

**期限**：材料是 House／HouseEtc 現值，**S3b（house 三表停寫）後就沒了**，
`last_fingerprint` 的來源 `HouseEtc.list_dict` 更在 S2 就 drop。所以這是一次性工具。

**這是「永不改寫別輪」的顯式例外**（同 `tools/backfill_vendor_extra.py`）：它改寫
既有的 snapshot 日檔。安全界線兩條——
  1. **只填 NULL，不覆蓋既有值**（DB 也是 NULL 就維持 NULL：從未 detail 的戶照舊）
  2. **只有 `days_absent` 會被改寫**，且僅限「`last_seen_at` 本來是 NULL、這次填上了」
     的列（即復活列），因為那個值是從復活日數起的、已知為錯

    manage.py snapshotcarryfill [--date D] [--vendor] [--dry-run] [--no-upload]
'''
import os
import sys
from datetime import date as date_cls, datetime, time as time_cls, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from rental import artifacts, contracts
from rental.models import House, HouseEtc, Vendor
from rental.raws import vendor_dirname

CARRY_FIELDS = ('first_seen_at', 'last_detail_at', 'last_seen_at', 'last_fingerprint',
                'fingerprint_at_last_detail', 'days_absent')


class Command(BaseCommand):
    help = 'Fill NULL carry columns of a snapshot day file from House/HouseEtc (one-off)'

    def add_arguments(self, parser):
        parser.add_argument('--date')
        parser.add_argument('--vendor', default='591 租屋網')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--no-upload', action='store_true')
        parser.add_argument('--values', action='store_true',
                            help='連 parsed 值欄一起補（來源＝該日 HouseTS，見 fill_values）')

    def handle(self, *_args, **options):
        # 雲上 stdout 是 block-buffered：不設行緩衝就完全看不到進度，慢的時候只能瞎等
        # （2026-09-18 為此瞎等一個 17 分鐘的 task）
        sys.stdout.reconfigure(line_buffering=True)
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
        date_str = day.isoformat()
        read_bucket = os.environ.get('TWRH_RAW_BUCKET')

        rows = artifacts.read_snapshot(short, date_str, read_bucket)
        if rows is None:
            raise CommandError('snapshot {} {} 不存在（本地與 S3 都沒有）'.format(short, date_str))

        if options['values']:
            self.fill_values(vendor, short, day, rows)

        targets = [r for r in rows
                   if any(r.get(f) is None for f in CARRY_FIELDS if f != 'days_absent')]
        print('=== snapshotcarryfill {} {}: {} 列，其中 {} 列有 NULL carry 欄'.format(
            short, date_str, len(rows), len(targets)))
        if not targets:
            if options['values'] and not options['dry_run']:
                self.write(rows, short, date_str, read_bucket, options)
            return

        day_end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time_cls.min))
        houses, fingerprints = self.load_db(vendor, [r['vendor_house_id'] for r in targets])
        filled = {f: 0 for f in CARRY_FIELDS}
        no_db = 0
        samples = []
        for row in targets:
            house = houses.get(row['vendor_house_id'])
            if house is None:
                no_db += 1
                continue
            before = {f: row.get(f) for f in CARRY_FIELDS}
            self.fill_row(row, house, fingerprints.get(row['vendor_house_id']), day, day_end)
            changed = [f for f in CARRY_FIELDS if row.get(f) != before[f]]
            for f in changed:
                filled[f] += 1
            if changed and len(samples) < 5:
                samples.append((row['vendor_house_id'],
                                {f: (before[f], row.get(f)) for f in changed}))

        for f in CARRY_FIELDS:
            print('    {:<28} 填 {}'.format(f, filled[f]))
        if no_db:
            print('    House 查不到（不動）: {}'.format(no_db))
        for hid, diff in samples:
            print('    例 {}: {}'.format(hid, diff))

        if options['dry_run']:
            print('dry-run：不寫檔')
            return
        self.write(rows, short, date_str, read_bucket, options)

    def write(self, rows, short, date_str, read_bucket, options):
        path, n = artifacts.write_snapshot(rows, short, date_str)
        print('    寫回 {} （{} 列）'.format(path, n))
        bucket = None if options['no_upload'] else read_bucket
        if bucket:
            try:
                artifacts.upload_snapshot(bucket, short, date_str, path)
                print('    uploaded snapshot/{}/{}.parquet'.format(short, date_str))
            except Exception as err:  # noqa: BLE001
                print('!!! upload failed（本地檔已寫，可用 snapshotfold --reupload）: {}'.format(err))

    def fill_values(self, vendor, short, day, rows):
        '''--values：補 parsed 值欄的 NULL，來源＝**該日的 HouseTS**。

        為什麼需要（2026-09-18 首次 exportcheck 挖出來的）：9/16 synthts 回補之前，
        當日被 diff 模式 skip 的戶在 HouseTS 只有稀疏列，那些列摺進 snapshot 後
        fold 一路 carry，於是約 1,300 戶的座標／additional_fee／管理費／停車欄在
        snapshot 是 NULL 而 House 有值（snapshotcheck 的 `snapshot_null_db_set` 桶
        一直在報這件事；export 切 snapshot 後會變成公開資料的缺值）。

        來源選 HouseTS 而不是 House 現值：**HouseTS 按日分桶，本身就是「那一天」的
        狀態**，不必像 carry 欄那樣做日界防呆（House 現值對過去日不成立——9/17 的
        教訓）。`snapshot_db.bootstrap_rows(carry='ts')` 正是「該日 HouseTS ＋ 該日列
        推得出的 carry」，這裡只拿它的 parsed 值欄、只填 NULL 格。

        **持久性**：填在「昨日 final」才會被今晚的 fold 當 prev 讀下去；填今日
        provisional 只是讓當天的對帳看得到，今晚重摺就沒了（snapshotfold 每晚會把
        昨日重摺成 final、再摺今日）。兩份都填才兩件事都成立。
        '''
        from rental import snapshot_db
        value_fields = [name for name, _ in contracts.PARSED_FIELDS
                        if name not in ('vendor', 'vendor_house_id', 'date', 'run',
                                        'crawled_at', 'parser_version', 'parsed_version',
                                        'vendor_extra')]
        # 目標戶用哨兵挑，不是「任一值欄 NULL」——`has_parking` 之類本來就大多是 NULL
        # （2026-09-17 那天 71,570 列），那樣選會挑出 73,098 列＝又變全表查。
        # 哨兵＝`additional_fee`：任何一次成功的 detail 解析一定產出它；本機實測
        # 2026-09-17 的 snapshot 裡 `n_balcony`／`author_key` 的 NULL 集合與它**完全相同**
        # （各 2,911 列），那就是稀疏摺入的那一群。
        need = [r['vendor_house_id'] for r in rows if r.get('additional_fee') is None]
        src = snapshot_db.ts_value_rows(vendor, day, need)
        print('=== --values：{} 戶有 NULL 值欄，HouseTS 找到 {} 戶對照'.format(
            len(need), len(src)))
        filled = {}
        touched = 0
        for row in rows:
            ref = src.get(row['vendor_house_id'])
            if ref is None:
                continue
            hit = False
            for name in value_fields:
                if row.get(name) is None and ref.get(name) is not None:
                    row[name] = ref[name]
                    filled[name] = filled.get(name, 0) + 1
                    hit = True
            touched += 1 if hit else 0
        print('    {} 戶補到值'.format(touched))
        for name, n in sorted(filled.items(), key=lambda kv: -kv[1])[:12]:
            print('    {:<28} 補 {}'.format(name, n))

    def load_db(self, vendor, ids):
        houses, fingerprints = {}, {}
        for i in range(0, len(ids), 5000):
            chunk = ids[i:i + 5000]
            for h in House.objects.filter(vendor=vendor, vendor_house_id__in=chunk).only(
                    'vendor_house_id', 'created', 'detail_crawled_at', 'list_crawled_at',
                    'list_fingerprint_changed_at'):
                houses[h.vendor_house_id] = h
            for hid, list_dict in HouseEtc.objects.filter(
                    vendor=vendor, vendor_house_id__in=chunk).values_list(
                    'vendor_house_id', 'list_dict'):
                if list_dict:
                    fingerprints[hid] = contracts.list_fingerprint(list_dict)
        return houses, fingerprints

    def fill_row(self, row, house, fingerprint, day, day_end):
        '''對映與 snapshot_db.bootstrap_rows(carry='house') 同式——同一套語意只有一份。

        **日界防呆**：House 的 detail_crawled_at／list_crawled_at／指紋都是「現在」的值，
        對過去日不成立（snapshot_db 的 carry='ts' 就是為此才留 NULL）。只填早於該日結束
        的值——不然會把今天的觀測回填到昨天那份 snapshot（2026-09-17 dry-run 實例：
        16566581 的 last_detail_at 是 9/17 03:51 台北，差點被寫進 9/16 的檔）。'''
        def before_day_end(value):
            return value if value is not None and value < day_end else None

        seen_was_null = row.get('last_seen_at') is None
        if row.get('first_seen_at') is None:
            # created 是列插入時間，必然早於該日（戶存在才有那天的列）
            row['first_seen_at'] = house.created
        if row.get('last_detail_at') is None:
            row['last_detail_at'] = before_day_end(house.detail_crawled_at)
        if row.get('last_seen_at') is None:
            row['last_seen_at'] = before_day_end(house.list_crawled_at)
        fp_changed = house.list_fingerprint_changed_at
        if row.get('last_fingerprint') is None and fingerprint is not None \
                and (fp_changed is None or fp_changed < day_end):
            # 指紋是現值：該日之後才變過就不是那天的指紋
            row['last_fingerprint'] = fingerprint
        detail_at = row.get('last_detail_at')
        if row.get('fingerprint_at_last_detail') is None and detail_at is not None \
                and row.get('last_fingerprint') is not None \
                and (fp_changed is None or fp_changed <= detail_at):
            row['fingerprint_at_last_detail'] = row['last_fingerprint']
        # days_absent 只在「復活列」重算：它原本從復活日數起，已知為錯
        if seen_was_null and row.get('last_seen_at') is not None:
            if row.get('source') == 'list':
                row['days_absent'] = 0
            else:
                row['days_absent'] = max(
                    (day - timezone.localtime(row['last_seen_at']).date()).days, 0)
