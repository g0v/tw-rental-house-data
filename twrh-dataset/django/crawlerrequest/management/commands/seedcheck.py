'''seedcheck：用純函數（rental.seeding）從當日 list stub 重算 detail seeds，
與 DB 版判準實際排進 queue 的種子比對（4a 驗收：兩軌一致）。

    manage.py seedcheck [--date] [--refresh-days 7] [--strict]

排在 flow 的 seed stage 之後、detail 之前——此刻 DB 狀態與 seed 當下相同
（detail 還沒動 detail_crawled_at）。預設 advisory（永遠 exit 0，只印
結果）；--strict 不一致即 exit 1，切換 seeding 路徑前才開。

過渡期轉接：每戶狀態由 House 欄位組 HouseState；昨日在列集合優先讀昨日
stub 檔，沒有（4a 上線首日）就退回 HouseTS 昨日 list 列並標 source。
'''
import json
import os
import sys
from datetime import date as date_cls, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from crawlerrequest.enums import RequestType
from crawlerrequest.models import RequestTS
from rental import artifacts, enums, seeding
from rental.models import House, HouseTS, Vendor
from rental.raws import vendor_dirname


class Command(BaseCommand):
    help = 'Recompute detail seeds from list stubs (pure function) and compare with queue'

    def add_arguments(self, parser):
        parser.add_argument('--date')
        parser.add_argument('--vendor', default='591 租屋網')
        parser.add_argument('--refresh-days', type=int,
                            default=int(os.environ.get('TWRH_DETAIL_REFRESH_DAYS', '7')))
        parser.add_argument('--strict', action='store_true')
        parser.add_argument('--sample', type=int, default=5,
                            help='不一致時各印幾個 house_id')

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
        bucket = os.environ.get('TWRH_RAW_BUCKET')
        yesterday = day - timedelta(days=1)

        today_stubs = list(artifacts.read_list_stubs(short, day.isoformat(), bucket))
        if not today_stubs:
            print('seedcheck: no list stubs for {} — skip (4a not yet producing?)'.format(day))
            return

        # 昨日在列集合：只有昨日「全量 run」的 stub 分區存在才用 stub（sweep 只掃前緣，
        # 拿子集當昨日在列會把幾乎全部判成回列／缺席——2026-09-10 4a 首日實踩：
        # only_pure 26,161 全是這兩類）；否則退回 HouseTS
        y_files = artifacts.list_partition_files(short, yesterday.isoformat(), bucket)
        y_has_full = any(os.path.basename(f).startswith('run.') for f in y_files)
        y_stubs = list(artifacts.read_list_stubs(short, yesterday.isoformat(), bucket)) \
            if y_has_full else []
        if y_stubs:
            yesterday_ids = set(seeding.latest_fingerprints(y_stubs))
            yesterday_source = 'stubs'
        else:
            yesterday_ids = set(HouseTS.objects.filter(
                vendor=vendor, year=yesterday.year, month=yesterday.month,
                day=yesterday.day, list_crawled_at__isnull=False,
            ).values_list('vendor_house_id', flat=True))
            yesterday_source = 'house_ts'

        # 只載 OPENED：select_seeds 四類全部先交集 open_ids，非 OPENED 列載了也用不到；
        # House 是全歷史（2026-09-11 雲上 853 萬列 vs OPENED 7.1 萬），全載＝每戶一個
        # HouseState 撐破 2 GB task memory（9/11 seedcheck 兩次 exit 137 OOM）
        state = {}
        for hid, crawled, fp_changed in House.objects.filter(
                vendor=vendor, deal_status=enums.DealStatusType.OPENED).values_list(
                'vendor_house_id', 'detail_crawled_at',
                'list_fingerprint_changed_at').iterator(chunk_size=20000):
            state[hid] = seeding.HouseState(
                open=True,
                detail_crawled_at=crawled,
                fingerprint_changed_at=fp_changed)

        db_rows = RequestTS.objects.filter(
            vendor=vendor, request_type=RequestType.DETAIL,
            year=day.year, month=day.month, day=day.day)
        # 「現在」釘在 DB 生種子的時刻：stale 判準是 detail_crawled_at < now−refresh_days，
        # seedcheck 晚幾分鐘跑就會多算幾百戶（2026-09-10：晚 3 分鐘 +756）
        seeded_at = db_rows.order_by('created').values_list('created', flat=True).first()
        now = seeded_at or timezone.now()
        result = seeding.select_seeds(
            today_stubs, yesterday_ids, state, now,
            refresh_days=options['refresh_days'])

        db_seeds = set(db_rows.values_list('seed__id', flat=True))

        only_pure = sorted(result.seeds - db_seeds)
        only_db = sorted(db_seeds - result.seeds)
        report = {
            'date': day.isoformat(),
            'stubs': len(today_stubs),
            'in_list': result.n_in_list,
            'open': result.n_open,
            'classes': {
                'stale': len(result.stale), 'fingerprint': len(result.fingerprint),
                'absent': len(result.absent), 'returned': len(result.returned)},
            'pure_seeds': len(result.seeds),
            'db_seeds': len(db_seeds),
            'skipped': result.skipped,
            'only_pure': len(only_pure),
            'only_db': len(only_db),
            'yesterday_source': yesterday_source,
            'now': now.isoformat(timespec='seconds'),
        }
        agree = not only_pure and not only_db
        print('seedcheck: {} — {}'.format('AGREE' if agree else 'DIFF',
                                          json.dumps(report, ensure_ascii=False)))
        n = options['sample']
        if only_pure:
            print('seedcheck: only in pure function (sample): {}'.format(only_pure[:n]))
        if only_db:
            print('seedcheck: only in DB queue (sample): {}'.format(only_db[:n]))
        if not agree and options['strict']:
            sys.exit(1)
