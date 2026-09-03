'''rawpack：把當日 raw scratch 打成日包（architecture-roadmap 3-1 finalize）。

    <TWRH_RAW_DIR>/<vendor>/<date>.tar.zst ＋ <date>.index.jsonl

方案 A（2026-09-03 拍板）：worker 各自寫 scratch，收尾單一打包——
一日一檔、完成判據純粹（檔案存在＝該 stage 完成）、單流壓縮率最佳。
同日重跑＝覆蓋（versioning 不開，拍板）。壓縮框架＝整包拉回：debug
點查＝拉當日包解開，不採可尋址壓縮、不依賴 S3 特有功能。

index.jsonl：每 member 一行 {"house_id", "member", "bytes"}——
「回頭多抓一欄」的重算保險與 debug 點查入口。

雙寫對帳（--reconcile）：抽樣比對包內容 vs DB HouseEtc raw 欄位
byte 級一致，並列出 member 數 vs 當日 queue DONE 數；AWS 對帳週
以此驗收，之後 DB 停寫 raw（cutover）。

TWRH_RAW_BUCKET 有設時上傳 S3（key: raw/<vendor>/<date>.tar.zst），
上傳成功後預設刪本地包（EFS 空間）；--keep-local 保留。
用法：
  python django/manage.py rawpack [--date YYYY-MM-DD] [--reconcile]
      [--keep-local] [--keep-scratch]
'''
import io
import json
import os
import random
import subprocess
import tarfile
from datetime import date as date_cls, datetime

from django.core.management.base import BaseCommand, CommandError

from rental import raws as raw_sink
from rental.raws import raw_dir
from rental.models import HouseEtc, Vendor
from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestType, RequestStatus

SAMPLE_SIZE = 20


class Command(BaseCommand):
    help = 'Pack the day\'s raw scratch into raw/<vendor>/<date>.tar.zst + index'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD（預設 TWRH_TARGET_DATE／今天）')
        parser.add_argument('--reconcile', action='store_true',
                            help='抽樣比對包內容 vs DB raw 欄位（雙寫對帳）')
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

        scratch_base = raw_sink.scratch_dir()
        vendors = []
        if os.path.isdir(scratch_base):
            for name in sorted(os.listdir(scratch_base)):
                if os.path.isdir(os.path.join(scratch_base, name, date_str)):
                    vendors.append(name)
        if not vendors:
            print('no raw scratch for {}, nothing to pack'.format(date_str))
            return

        for vendor in vendors:
            self.pack_vendor(vendor, date_str, options)

    def pack_vendor(self, vendor, date_str, options):
        src_dir = raw_sink.day_dir(vendor, date_str)
        names = sorted(
            n for n in os.listdir(src_dir)
            if n.endswith('.html'))
        if not names:
            print('{} {}: empty scratch, skip'.format(vendor, date_str))
            return

        out_dir = os.path.join(raw_dir(), vendor)
        os.makedirs(out_dir, exist_ok=True)
        pack_path = os.path.join(out_dir, date_str + '.tar.zst')
        index_path = os.path.join(out_dir, date_str + '.index.jsonl')
        print('=== {} {}: {} pages -> {}'.format(
            vendor, date_str, len(names), pack_path))

        # 同日重跑＝覆蓋（先寫 tmp 再 rename，避免半包）
        tmp_pack = pack_path + '.tmp'
        proc = subprocess.Popen(['zstd', '-q', '-3', '-f', '-o', tmp_pack],
                                stdin=subprocess.PIPE)
        tar = tarfile.open(mode='w|', fileobj=proc.stdin)
        index = []
        for name in names:
            path = os.path.join(src_dir, name)
            with open(path, 'rb') as f:
                data = f.read()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = int(os.path.getmtime(path))
            tar.addfile(info, io.BytesIO(data))
            house_id, kind, _ = name.rsplit('.', 2)
            index.append(
                {'house_id': house_id, 'member': name, 'bytes': len(data)})
        tar.close()
        proc.stdin.close()
        if proc.wait() != 0:
            raise CommandError('zstd failed')
        os.replace(tmp_pack, pack_path)

        with open(index_path, 'w') as f:
            for entry in index:
                f.write(json.dumps(entry) + '\n')

        self.verify_pack(pack_path, src_dir, index)
        if options['reconcile']:
            self.reconcile(vendor, date_str, index)

        if not options['keep_scratch']:
            for name in os.listdir(src_dir):
                os.unlink(os.path.join(src_dir, name))
            os.rmdir(src_dir)

        size = os.path.getsize(pack_path)
        print('    OK — {} members packed ({:.1f} MB)'.format(
            len(index), size / 2**20))

        bucket = os.environ.get('TWRH_RAW_BUCKET')
        if bucket:
            self.upload(bucket, vendor, date_str, pack_path, index_path,
                        options['keep_local'])

    def verify_pack(self, pack_path, src_dir, index):
        '''member 數對 index、抽樣 byte 級比對 scratch 原檔。'''
        listed = subprocess.run(['tar', '-I', 'zstd', '-tf', pack_path],
                                capture_output=True, text=True, check=True)
        n_members = len(listed.stdout.splitlines())
        if n_members != len(index):
            raise CommandError(
                'pack member {} != index {}'.format(n_members, len(index)))
        for entry in random.sample(index, min(SAMPLE_SIZE, len(index))):
            out = subprocess.run(
                ['tar', '-I', 'zstd', '-xOf', pack_path, entry['member']],
                capture_output=True, check=True)
            with open(os.path.join(src_dir, entry['member']), 'rb') as f:
                if out.stdout != f.read():
                    raise CommandError(
                        '{} content mismatch vs scratch'.format(entry['member']))

    def reconcile(self, vendor, date_str, index):
        '''雙寫對帳：包內容 vs DB raw 欄位抽樣 byte 比對＋量的對照。'''
        vendor_obj = Vendor.objects.filter(name__startswith=vendor).first()
        if vendor_obj is None:
            raise CommandError('vendor {} not in DB'.format(vendor))

        # vendor 參數是目錄短名（'591'），DB 查全名（'591 租屋網'）
        detail_entries = [e for e in index if e['member'].endswith('.detail.html')]
        sample = random.sample(
            detail_entries, min(SAMPLE_SIZE, len(detail_entries)))
        mismatch = 0
        for entry in sample:
            etc = HouseEtc.objects.filter(
                vendor=vendor_obj, vendor_house_id=entry['house_id']).first()
            if etc is None or not etc.detail_raw:
                mismatch += 1
                print('    reconcile: DB 無 raw — {}'.format(entry['member']))
                continue
            pack_path = os.path.join(
                raw_dir(), vendor, date_str + '.tar.zst')
            out = subprocess.run(
                ['tar', '-I', 'zstd', '-xOf', pack_path, entry['member']],
                capture_output=True, check=True)
            if out.stdout != etc.detail_raw.encode('utf-8'):
                mismatch += 1
                print('    reconcile: byte 不一致 — {}'.format(entry['member']))
        if mismatch:
            raise CommandError(
                'reconcile failed: {}/{} sampled members differ from DB'.format(
                    mismatch, len(sample)))

        day = datetime.strptime(date_str, '%Y-%m-%d')
        n_done = RequestTS.objects.filter(
            year=day.year, month=day.month, day=day.day,
            vendor=vendor_obj, request_type=RequestType.DETAIL,
            status=RequestStatus.DONE).count()
        print('    reconcile OK — sample {} 一致；detail members {} '
              'vs queue done {}（NOT_FOUND 等無 raw 頁屬正常差）'.format(
                  len(sample), len(detail_entries), n_done))

    def upload(self, bucket, vendor, date_str, pack_path, index_path,
               keep_local):
        import boto3
        s3 = boto3.client('s3')
        for path in (pack_path, index_path):
            key = 'raw/{}/{}'.format(vendor, os.path.basename(path))
            s3.upload_file(path, bucket, key)
            print('    uploaded s3://{}/{}'.format(bucket, key))
            if not keep_local:
                os.unlink(path)
