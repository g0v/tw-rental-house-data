'''rawpack：把當日 raw scratch 打成日包（architecture-roadmap 3-1 finalize）。

    <TWRH_RAW_DIR>/<vendor>/<date>.tar.zst ＋ <date>.index.jsonl

方案 A（2026-09-03 拍板）：worker 各自寫 scratch，收尾單一打包——
一日一檔、完成判據純粹（檔案存在＝該 stage 完成）、單流壓縮率最佳。
壓縮框架＝整包拉回：debug 點查＝拉當日包解開，不採可尋址壓縮、
不依賴 S3 特有功能。

**同日多次 run＝聯集**（2026-09-05 補，前緣掃描上線後）：同一天日跑之外
還有數輪 sweep，各自 rawpack。當日既有日包（本地或 S3）先合併回來，
scratch 的同名 member 蓋掉舊的（後爬者勝，與 DB 覆寫語意一致），再寫
新包覆蓋——舊 member 不丟。scratch 裡比目標日早的日期目錄（前一天
sweep 留下、沒人打包的孤兒）一併各自打包。

index.jsonl：每 member 一行 {"house_id", "member", "bytes"}——
「回頭多抓一欄」的重算保險與 debug 點查入口。

雙寫對帳（--reconcile）：比對包內容 vs DB HouseEtc raw 欄位 byte 級一致
（預設抽樣、--full 全量串流），並列 member 數 vs 當日 queue DONE 數。
--reconcile-only：不打包，對既有日包（本地沒有就從 S3 拉）做同樣比對——
D5 cutover 前對歷史日包補跑全量對帳用。TWRH_RAW_DB_WRITE=0（cutover 後）
DB 沒 raw 可比，只報量。

TWRH_RAW_BUCKET 有設時上傳 S3（key: raw/<vendor>/<date>.tar.zst），
上傳成功後預設刪本地包（EFS 空間）；--keep-local 保留。
用法：
  python django/manage.py rawpack [--date YYYY-MM-DD] [--reconcile [--full]]
      [--keep-local] [--keep-scratch]
  python django/manage.py rawpack --reconcile-only --full --date 2026-09-04
'''
import io
import json
import os
import random
import subprocess
import tarfile
from datetime import date as date_cls, datetime, time as time_cls, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from rental import raws as raw_sink
from rental.raws import raw_dir, vendor_dirname
from rental.models import HouseEtc, Vendor
from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestType, RequestStatus

SAMPLE_SIZE = 20


def iter_pack(pack_path):
    '''串流展開日包，yield (member_name, bytes)。'''
    proc = subprocess.Popen(['zstd', '-dcq', pack_path], stdout=subprocess.PIPE)
    with tarfile.open(mode='r|', fileobj=proc.stdout) as tar:
        for info in tar:
            if info.isfile():
                yield info.name, tar.extractfile(info).read()
    if proc.wait() != 0:
        raise CommandError('zstd failed on {}'.format(pack_path))


def pack_paths(vendor, date_str):
    out_dir = os.path.join(raw_dir(), vendor)
    return (os.path.join(out_dir, date_str + '.tar.zst'),
            os.path.join(out_dir, date_str + '.index.jsonl'))


class Command(BaseCommand):
    help = 'Pack the day\'s raw scratch into raw/<vendor>/<date>.tar.zst + index'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD（預設 TWRH_TARGET_DATE／今天）')
        parser.add_argument('--reconcile', action='store_true',
                            help='比對包內容 vs DB raw 欄位（雙寫對帳）')
        parser.add_argument('--reconcile-only', action='store_true',
                            help='不打包，只對既有日包（本地或 S3）做對帳')
        parser.add_argument('--full', action='store_true',
                            help='對帳全量串流比對（預設抽樣 {}）'.format(SAMPLE_SIZE))
        parser.add_argument('--keep-scratch', action='store_true',
                            help='打包後保留 scratch（預設刪除）')
        parser.add_argument('--keep-local', action='store_true',
                            help='上傳 S3 後保留本地包（預設刪除）')

    def handle(self, *_args, **options):
        if options['date']:
            try:
                datetime.strptime(options['date'], '%Y-%m-%d')
            except ValueError:
                raise CommandError('--date 需為 YYYY-MM-DD')
            date_str = options['date']
        else:
            date_str = os.environ.get(
                'TWRH_TARGET_DATE') or date_cls.today().isoformat()

        if options['reconcile_only']:
            vendors = sorted({vendor_dirname(v.name)
                              for v in Vendor.objects.all()})
            for vendor in vendors:
                self.reconcile_existing(vendor, date_str, options)
            return

        # scratch/<vendor dir>/<date>/：vendor 目錄正規化成短名（舊版曾用全名
        # '591 租屋網'，同一 vendor 的多個目錄合併）；日期取 <= 目標日——
        # 早於目標日的是前一天 sweep 留下沒打包的孤兒，各自併回該日日包
        scratch_base = raw_sink.scratch_dir()
        jobs = {}   # (vendor短名, date) -> [scratch day dir, ...]
        if os.path.isdir(scratch_base):
            for dirname in sorted(os.listdir(scratch_base)):
                vdir = os.path.join(scratch_base, dirname)
                if not os.path.isdir(vdir):
                    continue
                for day in sorted(os.listdir(vdir)):
                    if day <= date_str and os.path.isdir(os.path.join(vdir, day)):
                        jobs.setdefault((vendor_dirname(dirname), day), []).append(
                            os.path.join(vdir, day))
        if not jobs:
            print('no raw scratch for {}, nothing to pack'.format(date_str))
            return
        for (vendor, day), src_dirs in sorted(jobs.items()):
            if day != date_str:
                print('=== orphan scratch {} {} (before target {}), packing too'.format(
                    vendor, day, date_str))
            self.pack_vendor(vendor, day, src_dirs, options)

    # ---- packing ---------------------------------------------------------

    def existing_pack(self, vendor, date_str):
        '''當日既有日包路徑（本地優先；沒有就從 S3 拉回）；都沒有回 None。'''
        pack_path, index_path = pack_paths(vendor, date_str)
        if os.path.exists(pack_path):
            return pack_path
        bucket = os.environ.get('TWRH_RAW_BUCKET')
        if not bucket:
            return None
        import boto3
        from botocore.exceptions import ClientError
        s3 = boto3.client('s3')
        key = 'raw/{}/{}'.format(vendor, os.path.basename(pack_path))
        try:
            s3.head_object(Bucket=bucket, Key=key)
        except ClientError as err:
            if err.response['Error']['Code'] in ('404', 'NoSuchKey', 'NotFound'):
                return None
            raise
        os.makedirs(os.path.dirname(pack_path), exist_ok=True)
        s3.download_file(bucket, key, pack_path)
        print('    merged base: s3://{}/{} pulled'.format(bucket, key))
        return pack_path

    def pack_vendor(self, vendor, date_str, src_dirs, options):
        # member -> scratch path；多個 scratch 目錄同名 member 時後者勝
        sources = {}
        for src_dir in src_dirs:
            for name in sorted(os.listdir(src_dir)):
                if name.endswith('.html'):
                    sources[name] = os.path.join(src_dir, name)
        if not sources:
            print('{} {}: empty scratch, skip'.format(vendor, date_str))
            self.cleanup_scratch(src_dirs, options)
            return

        pack_path, index_path = pack_paths(vendor, date_str)
        os.makedirs(os.path.dirname(pack_path), exist_ok=True)
        base_pack = self.existing_pack(vendor, date_str)
        print('=== {} {}: {} pages in scratch{} -> {}'.format(
            vendor, date_str, len(sources),
            ' + merge existing pack' if base_pack else '', pack_path))

        # 先寫 tmp 再 rename，避免半包；舊包（若有）串流讀、不整包進記憶體
        tmp_pack = pack_path + '.tmp'
        proc = subprocess.Popen(['zstd', '-q', '-3', '-f', '-o', tmp_pack],
                                stdin=subprocess.PIPE)
        tar = tarfile.open(mode='w|', fileobj=proc.stdin)
        index = []
        carried = 0

        def add(name, data, mtime):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = mtime
            tar.addfile(info, io.BytesIO(data))
            house_id, _kind, _ = name.rsplit('.', 2)
            index.append({'house_id': house_id, 'member': name, 'bytes': len(data)})

        if base_pack:
            for name, data in iter_pack(base_pack):
                if name in sources:
                    continue   # scratch 的較新，後爬者勝
                add(name, data, int(datetime.now().timestamp()))
                carried += 1
        for name in sorted(sources):
            path = sources[name]
            with open(path, 'rb') as f:
                add(name, f.read(), int(os.path.getmtime(path)))
        tar.close()
        proc.stdin.close()
        if proc.wait() != 0:
            raise CommandError('zstd failed')
        os.replace(tmp_pack, pack_path)

        with open(index_path, 'w') as f:
            for entry in index:
                f.write(json.dumps(entry) + '\n')

        fresh = [e for e in index if e['member'] in sources]
        self.verify_pack(pack_path, sources, index, fresh)
        if options['reconcile']:
            self.reconcile(vendor, date_str, pack_path, fresh, options['full'])

        self.cleanup_scratch(src_dirs, options)

        size = os.path.getsize(pack_path)
        print('    OK — {} members packed ({} fresh, {} carried; {:.1f} MB)'.format(
            len(index), len(fresh), carried, size / 2**20))

        bucket = os.environ.get('TWRH_RAW_BUCKET')
        if bucket:
            self.upload(bucket, vendor, pack_path, index_path, options['keep_local'])

    def cleanup_scratch(self, src_dirs, options):
        if options['keep_scratch']:
            return
        for src_dir in src_dirs:
            for name in os.listdir(src_dir):
                os.unlink(os.path.join(src_dir, name))
            os.rmdir(src_dir)

    def verify_pack(self, pack_path, sources, index, fresh):
        '''member 數對 index、抽樣 byte 級比對 scratch 原檔。'''
        listed = subprocess.run(['tar', '-I', 'zstd', '-tf', pack_path],
                                capture_output=True, text=True, check=True)
        n_members = len(listed.stdout.splitlines())
        if n_members != len(index):
            raise CommandError(
                'pack member {} != index {}'.format(n_members, len(index)))
        for entry in random.sample(fresh, min(SAMPLE_SIZE, len(fresh))):
            out = subprocess.run(
                ['tar', '-I', 'zstd', '-xOf', pack_path, entry['member']],
                capture_output=True, check=True)
            with open(sources[entry['member']], 'rb') as f:
                if out.stdout != f.read():
                    raise CommandError(
                        '{} content mismatch vs scratch'.format(entry['member']))

    # ---- reconcile -------------------------------------------------------

    def reconcile_existing(self, vendor, date_str, options):
        pack_path = self.existing_pack(vendor, date_str)
        if pack_path is None:
            print('{} {}: no pack (local or S3), skip'.format(vendor, date_str))
            return
        _pack, index_path = pack_paths(vendor, date_str)
        if not os.path.exists(index_path):
            bucket = os.environ.get('TWRH_RAW_BUCKET')
            if bucket:
                import boto3
                boto3.client('s3').download_file(
                    bucket, 'raw/{}/{}'.format(vendor, os.path.basename(index_path)),
                    index_path)
        with open(index_path) as f:
            index = [json.loads(line) for line in f if line.strip()]
        print('=== reconcile {} {}: {} members in pack'.format(
            vendor, date_str, len(index)))
        self.reconcile(vendor, date_str, pack_path, index, options['full'])
        if not options['keep_local']:
            os.unlink(pack_path)
            os.unlink(index_path)

    def reconcile(self, vendor, date_str, pack_path, candidates, full):
        '''雙寫對帳：包內容 vs DB raw 欄位 byte 比對＋量的對照。

        candidates：要比的 index entries（打包時＝本輪 scratch 的；
        --reconcile-only＝整包）。該日之後又爬過（detail_crawled_at 晚於
        當日）的物件 DB 已是新 raw，算 superseded 跳過不算錯。
        '''
        vendor_obj = Vendor.objects.filter(name__startswith=vendor).first()
        if vendor_obj is None:
            raise CommandError('vendor {} not in DB'.format(vendor))
        day = datetime.strptime(date_str, '%Y-%m-%d')
        day_end = timezone.make_aware(
            datetime.combine(day.date() + timedelta(days=1), time_cls.min))

        detail_entries = [e for e in candidates
                          if e['member'].endswith('.detail.html')]
        n_done = RequestTS.objects.filter(
            year=day.year, month=day.month, day=day.day,
            vendor=vendor_obj, request_type=RequestType.DETAIL,
            status=RequestStatus.DONE).count()

        if not raw_sink.db_write():
            print('    reconcile: TWRH_RAW_DB_WRITE=0，DB 無 raw 可比，只報量——'
                  'detail members {} vs queue done {}'.format(
                      len(detail_entries), n_done))
            return

        if full:
            targets = {e['member'] for e in detail_entries}
        else:
            targets = {e['member'] for e in random.sample(
                detail_entries, min(SAMPLE_SIZE, len(detail_entries)))}

        def db_raw(member):
            house_id = member.rsplit('.', 2)[0]
            etc = HouseEtc.objects.select_related('house').filter(
                vendor=vendor_obj, vendor_house_id=house_id).first()
            return etc

        mismatch = superseded = missing = compared = 0

        def check(member, data):
            nonlocal mismatch, superseded, missing, compared
            etc = db_raw(member)
            crawled = etc.house.detail_crawled_at if etc else None
            if crawled is not None and crawled >= day_end:
                superseded += 1
                return
            if etc is None or not etc.detail_raw:
                missing += 1
                print('    reconcile: DB 無 raw — {}'.format(member))
                return
            compared += 1
            if data != etc.detail_raw.encode('utf-8'):
                mismatch += 1
                print('    reconcile: byte 不一致 — {}'.format(member))

        if full:
            for name, data in iter_pack(pack_path):
                if name in targets:
                    check(name, data)
        else:
            for member in sorted(targets):
                out = subprocess.run(
                    ['tar', '-I', 'zstd', '-xOf', pack_path, member],
                    capture_output=True, check=True)
                check(member, out.stdout)

        summary = ('{} compared, {} superseded (re-crawled later), {} no raw in DB'
                   .format(compared, superseded, missing))
        if mismatch or missing:
            raise CommandError(
                'reconcile failed: {} mismatch — {}'.format(mismatch, summary))
        print('    reconcile OK ({}) — {}；detail members {} vs queue done {}'
              '（NOT_FOUND 等無 raw 頁屬正常差）'.format(
                  'full' if full else 'sample', summary,
                  len(detail_entries), n_done))

    # ---- upload ----------------------------------------------------------

    def upload(self, bucket, vendor, pack_path, index_path, keep_local):
        import boto3
        s3 = boto3.client('s3')
        for path in (pack_path, index_path):
            key = 'raw/{}/{}'.format(vendor, os.path.basename(path))
            s3.upload_file(path, bucket, key)
            print('    uploaded s3://{}/{}'.format(bucket, key))
            if not keep_local:
                os.unlink(path)
