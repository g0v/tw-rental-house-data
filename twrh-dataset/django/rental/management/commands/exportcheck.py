'''exportcheck（S3a 驗收）：同一區間由 DB 路徑與 snapshot 路徑各出一份 CSV，
排序正規化後逐 byte 比對。advisory——印 AGREE｜DIFF 給 flow 的 advisory_check 收，不擋 pipeline。

**為什麼一定要排在 flow 的 snapshot stage 之後、當日 sweep 之前**：DB 路徑讀的是
`House` 的「現在」，snapshot 路徑讀的是某一天的檔。兩邊只有在「今日分區剛摺成
provisional、而今天的 sweep 還沒再動 DB」那個空檔才對齊。窗尾因此固定取今天
（`TWRH_TARGET_DATE`），不是昨天——取昨天的話，今天已爬過的戶在 DB 是今天的值、
在 snapshot 是昨天的值，會報出一堆假差異。

三欄是刻意的差異（2026-09-17 維護者拍板，見 snapshot_source）：物件首次發現時間／
物件最後更新時間／刊登者編碼。預設略過它們比，`--strict-columns` 可連它們一起比。

用法：
  python django/manage.py exportcheck [--date YYYY-MM-DD] [--days 3] [--keep]
  python django/manage.py exportcheck --from 2026-09-01 --to 2026-09-17   # 月窗（出貨前）
'''
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from rental.libs.export import RawExport

REPO_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..'))
COMPARE = os.path.join(REPO_ROOT, 'tools', 'compare_export.py')


class Command(BaseCommand):
    help = 'S3a: compare DB-path and snapshot-path export of the same window'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='窗尾（預設 TWRH_TARGET_DATE／今天）')
        parser.add_argument('--days', type=int, default=3,
                            help='窗長，預設 3 天（含窗尾）')
        parser.add_argument('--from', dest='from_date', help='窗首 YYYY-MM-DD，蓋過 --days')
        parser.add_argument('--to', dest='to_date', help='窗尾 YYYY-MM-DD，蓋過 --date')
        parser.add_argument('--strict-columns', action='store_true',
                            help='連三個已知改對映的欄一起比')
        parser.add_argument('--keep', action='store_true', help='保留兩份 CSV')
        parser.add_argument('--strict', action='store_true',
                            help='DIFF 時 exit 1（預設 advisory exit 0）')

    def handle(self, *_args, **options):
        end = options['to_date'] or options['date'] or os.environ.get(
            'TWRH_TARGET_DATE') or timezone.localtime().date().isoformat()
        end_date = datetime.strptime(end, '%Y-%m-%d').date()
        if options['from_date']:
            start_date = datetime.strptime(options['from_date'], '%Y-%m-%d').date()
        else:
            start_date = end_date - timedelta(days=max(options['days'], 1) - 1)
        if start_date > end_date:
            raise CommandError('窗首晚於窗尾')

        from_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        to_dt = timezone.make_aware(
            datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

        tmp_dir = tempfile.mkdtemp(prefix='exportcheck-')
        paths = {}
        try:
            for source in ('db', 'snapshot'):
                out = os.path.join(tmp_dir, source)
                RawExport(source=source).print(
                    from_dt, to_dt, print_enum=False, outfile=out)
                paths[source] = out + '.csv'

            cmd = [sys.executable, COMPARE, paths['db'], paths['snapshot']]
            if not options['strict_columns']:
                cmd.append('--expect-mapped')
            proc = subprocess.run(cmd, capture_output=True, text=True)
            sys.stdout.write(proc.stdout)
            if proc.stderr:
                sys.stderr.write(proc.stderr)
            verdict = 'AGREE' if proc.returncode == 0 else 'DIFF'
            print('exportcheck: {} — window {}..{}'.format(verdict, start_date, end_date))
            if verdict == 'DIFF' and options['strict']:
                sys.exit(1)
        finally:
            if options['keep']:
                print('CSV 留在 {}'.format(tmp_dir))
            else:
                shutil.rmtree(tmp_dir, ignore_errors=True)
