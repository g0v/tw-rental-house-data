"""raw offload：把保留窗口外的 detail_raw/list_raw 打包出 DB（aws-deployment-plan 案 A）。

打包格式與遷移腳本（tools/migrate/strip_house_etc.py）一致：
  <output_dir>/<vendor>/<YYYY-MM>.tar.zst（member: <house_id>.detail.html / .list.html）
  ＋同名 .index.json（house_id → member → bytes）
月份取自 updated；重複刊登會刷新 updated，讓 raw 回到窗口內、之後隨新月份再歸檔。
同月份檔案已存在時加 -2、-3 序號（例：重刊聚積的補歸檔），查找時同月所有 index 都要看。

預設 dry-run（只打包＋驗證，不動 DB）；加 --commit 才會清空 raw 欄位並蓋
raw_archived_at 時戳。**不要與爬蟲並行執行**——打包與清欄位之間沒有鎖。

用法（S3 上傳由外層 wrapper 負責，本 command 只落地目錄）：
  python django/manage.py rawoffload <output_dir> [--days-ago 90] [--commit]
"""
import io
import json
import os
import random
import subprocess
import tarfile
import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

SAMPLE_SIZE = 20
STRIP_BATCH = 500


class Command(BaseCommand):
    help = 'Pack raw HTML beyond the retention window into tar.zst and strip it from DB.'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument('output_dir')
        parser.add_argument('-d', '--days-ago', dest='days_ago', type=int, default=90,
                            help='retention window, default 90 days')
        parser.add_argument('--commit', action='store_true',
                            help='actually strip raw columns after packing (default: dry-run)')
        parser.add_argument('--months', nargs='*',
                            help='only offload these YYYY-MM months')

    def handle(self, *args, **options):
        if not os.path.isdir(options['output_dir']):
            raise CommandError('Directory {} not existed'.format(options['output_dir']))
        cutoff = timezone.localtime() - timedelta(options['days_ago'])

        cur = connection.cursor()
        cur.execute(
            "select v.name, to_char(e.updated, 'YYYY-MM') as month, count(*) "
            "from house_etc e join vendor v on v.id = e.vendor_id "
            "where (e.detail_raw is not null or e.list_raw is not null) "
            "and e.updated < %s group by 1, 2 order by 1, 2", [cutoff])
        jobs = cur.fetchall()
        if not jobs:
            self.stdout.write('nothing beyond the retention window, done')
            return

        for vendor, month, n_rows in jobs:
            if options['months'] and month not in options['months']:
                continue
            self.offload_month(vendor, month, n_rows, cutoff, options)

    def offload_month(self, vendor, month, n_rows, cutoff, options):
        t0 = time.time()
        out_dir = os.path.join(options['output_dir'], vendor)
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.join(out_dir, month)
        pack_path = base + '.tar.zst'
        seq = 1
        while os.path.exists(pack_path):
            seq += 1
            pack_path = f'{base}-{seq}.tar.zst'
        index_path = pack_path.replace('.tar.zst', '.index.json')
        self.stdout.write(f'=== {vendor} {month}: {n_rows} rows -> {pack_path}')

        # named cursor 需要 transaction；atomic 收攏整月讀取
        with transaction.atomic():
            src = connection.connection.cursor(name=f'rawoffload_{month.replace("-", "")}')
            src.itersize = 200
            src.execute(
                "select e.house_id, e.updated, e.detail_raw, e.list_raw "
                "from house_etc e join vendor v on v.id = e.vendor_id "
                "where (e.detail_raw is not null or e.list_raw is not null) "
                "and e.updated < %s and v.name = %s "
                "and e.updated >= %s::date and e.updated < %s::date + interval '1 month'",
                [cutoff, vendor, month + '-01', month + '-01'])

            proc = subprocess.Popen(['zstd', '-q', '-3', '-f', '-o', pack_path],
                                    stdin=subprocess.PIPE)
            tar = tarfile.open(mode='w|', fileobj=proc.stdin)
            index = {}
            for house_id, updated, draw, lraw in src:
                entry = {}
                for kind, text in (('detail', draw), ('list', lraw)):
                    if not text:
                        continue
                    data = text.encode('utf-8')
                    info = tarfile.TarInfo(f'{house_id}.{kind}.html')
                    info.size = len(data)
                    info.mtime = int(updated.timestamp())
                    tar.addfile(info, io.BytesIO(data))
                    entry[info.name] = len(data)
                index[str(house_id)] = entry
            src.close()
            tar.close()
            proc.stdin.close()
            if proc.wait() != 0:
                raise CommandError('zstd failed')

        with open(index_path, 'w') as f:
            json.dump(index, f)
        self.verify_pack(pack_path, index)

        stripped = 0
        if options['commit']:
            ids = [int(k) for k in index]
            cur = connection.cursor()
            for i in range(0, len(ids), STRIP_BATCH):
                cur.execute(
                    'update house_etc set detail_raw = null, list_raw = null, '
                    'raw_archived_at = now() where house_id = any(%s)',
                    [ids[i:i + STRIP_BATCH]])
                stripped += cur.rowcount

        size = os.path.getsize(pack_path)
        self.stdout.write(
            f'    OK — {len(index)} rows packed ({size / 2**20:.0f} MB), '
            f'{stripped} rows stripped{"" if options["commit"] else " (dry-run)"}'
            f', {time.time() - t0:.0f}s')

    def verify_pack(self, pack_path, index):
        listed = subprocess.run(['tar', '-I', 'zstd', '-tf', pack_path],
                                capture_output=True, text=True, check=True)
        n_members = len(listed.stdout.splitlines())
        n_expected = sum(len(v) for v in index.values())
        if n_members != n_expected:
            raise CommandError(f'pack member {n_members} != index {n_expected}')

        cur = connection.cursor()
        for house_id in random.sample(list(index), min(SAMPLE_SIZE, len(index))):
            cur.execute('select detail_raw, list_raw from house_etc where house_id = %s',
                        [int(house_id)])
            draw, lraw = cur.fetchone()
            for kind, original in (('detail', draw), ('list', lraw)):
                member = f'{house_id}.{kind}.html'
                if member not in index[house_id]:
                    continue
                out = subprocess.run(['tar', '-I', 'zstd', '-xOf', pack_path, member],
                                     capture_output=True, check=True)
                if out.stdout != original.encode('utf-8'):
                    raise CommandError(f'{member} content mismatch')
