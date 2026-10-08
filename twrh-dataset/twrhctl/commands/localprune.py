'''localprune：清 EFS（本地）上已在 S3 的舊分區檔（2026-10-08）。

S3 是唯一真相來源，本地只是工作區；各讀取端（partition_files／_fetch_snapshot／
_fetch_latest／rawpack.existing_pack）本地沒有就從 S3 拉回。但之前沒有任何保留規則，
EFS 一個月從 3.5 GB 長到 8 GB（EFS 單價是 S3 標準的 13 倍）。

規則（日期取檔名／目錄名，以 TWRH_TARGET_DATE 為今天）：
  list／parsed／deals  artifacts/<tree>/<vendor>/<date>/      早於 keep 天 → 整個日目錄刪
  latest              artifacts/latest/<vendor>/daily/<date>.parquet   同上
  snapshot            artifacts/snapshot/<vendor>/<date>.parquet
                      另外**保留上個月 1 日起的全部**：export（twrhctl/export/snapshot_source）
                      只讀本地、缺檔靜默跳過，1 日出上月與月中重出都要整月在
  raws                raws/<vendor>/<date>.{tar.zst,index.jsonl}（rawpack 上傳後本來就刪，
                      這裡收 --keep-local 或上傳失敗留下的）
不碰：queue（只存在 EFS）、scratch、logs、manifests、datas、analysis 等其他目錄。

安全：每個檔都要 S3 上同 key 存在且大小相同才刪；日目錄是全有全無（partition_files
本地有任一檔就不回 S3 拉，刪一半會讓讀取端少讀 run）。沒設 TWRH_RAW_BUCKET＝不刪
（本機開發的檔可能是唯一一份）。

    python -m twrhctl localprune [--keep-days 7] [--dry-run]
'''
import os
import re
from datetime import datetime, timedelta

from twrhctl.base import BaseCommand
from twrhctl import tz

from rental import artifacts
from rental.raws import raw_dir

DATE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')
PARTITION_TREES = ('list', 'parsed', 'deals')


def _date_of(name):
    m = DATE_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), '%Y-%m-%d').date()
    except ValueError:
        return None


def _vendors(base):
    if not os.path.isdir(base):
        return []
    return sorted(v for v in os.listdir(base)
                  if v != 'scratch' and os.path.isdir(os.path.join(base, v)))


def _files(directory):
    return sorted(os.path.join(directory, n) for n in os.listdir(directory)
                  if os.path.isfile(os.path.join(directory, n)))


def plan(today, keep_days):
    '''[(label, [(local_path, s3_key), ...], remove_dir_or_None)]：每個單位全有全無。'''
    cutoff = today - timedelta(days=keep_days)
    prev_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    snapshot_cutoff = min(cutoff, prev_month_start)
    adir = artifacts.artifact_dir()
    units = []

    for tree in PARTITION_TREES:
        base = os.path.join(adir, tree)
        for vendor in _vendors(base):
            for name in sorted(os.listdir(os.path.join(base, vendor))):
                d = _date_of(name)
                ddir = os.path.join(base, vendor, name)
                if d is None or d >= cutoff or not os.path.isdir(ddir):
                    continue
                files = [(p, '{}/{}/{}/{}'.format(tree, vendor, name, os.path.basename(p)))
                         for p in _files(ddir)]
                units.append(('{}/{}/{}'.format(tree, vendor, name), files, ddir))

    for tree, sub, limit in (('snapshot', '', snapshot_cutoff), ('latest', 'daily', cutoff)):
        base = os.path.join(adir, tree)
        for vendor in _vendors(base):
            directory = os.path.join(base, vendor, sub)
            if not os.path.isdir(directory):
                continue
            for path in _files(directory):
                name = os.path.basename(path)
                d = _date_of(name)
                if d is None or d >= limit or not name.endswith('.parquet'):
                    continue
                key = '/'.join(p for p in (tree, vendor, sub, name) if p)
                units.append((key, [(path, key)], None))

    rdir = raw_dir()
    for vendor in _vendors(rdir):
        by_day = {}
        for path in _files(os.path.join(rdir, vendor)):
            name = os.path.basename(path)
            d = _date_of(name)
            if d is None or d >= cutoff or name[10:] not in ('.tar.zst', '.index.jsonl'):
                continue
            by_day.setdefault(name[:10], []).append(
                (path, 'raw/{}/{}'.format(vendor, name)))
        for day, files in sorted(by_day.items()):
            units.append(('raw/{}/{}'.format(vendor, day), files, None))
    return units


def s3_size(bucket, key):
    '''S3 物件大小；不存在回 None。'''
    import boto3
    from botocore.exceptions import ClientError
    try:
        return boto3.client('s3').head_object(Bucket=bucket, Key=key)['ContentLength']
    except ClientError as err:
        if err.response.get('Error', {}).get('Code') in ('404', 'NoSuchKey', 'NotFound'):
            return None
        raise


class Command(BaseCommand):
    help = 'delete local (EFS) partitions older than N days that are verified on S3'

    def add_arguments(self, parser):
        parser.add_argument('--keep-days', type=int,
                            default=int(os.environ.get('TWRH_LOCAL_KEEP_DAYS', '7')))
        parser.add_argument('--date', help='YYYY-MM-DD（預設 TWRH_TARGET_DATE／今天）')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *_args, **options):
        override = options['date'] or os.environ.get('TWRH_TARGET_DATE')
        today = (datetime.strptime(override, '%Y-%m-%d').date() if override
                 else tz.localtime().date())
        bucket = os.environ.get('TWRH_RAW_BUCKET')
        if not bucket:
            print('localprune: TWRH_RAW_BUCKET not set — nothing pruned（本地檔可能是唯一一份）')
            return
        units = plan(today, options['keep_days'])
        removed = kept = freed = 0
        for label, files, ddir in units:
            bad = [key for path, key in files if s3_size(bucket, key) != os.path.getsize(path)]
            if bad:
                kept += 1
                print('    KEEP {}: not on S3 or size differs: {}'.format(label, ', '.join(bad)))
                continue
            size = sum(os.path.getsize(path) for path, _ in files)
            if not options['dry_run']:
                for path, _ in files:
                    os.unlink(path)
                if ddir:
                    try:
                        os.rmdir(ddir)
                    except OSError:
                        pass
            removed += 1
            freed += size
        print('localprune {} keep_days={}{}: removed {} units ({:.1f} MB), kept {} unverified'.format(
            today, options['keep_days'], ' (dry-run)' if options['dry_run'] else '',
            removed, freed / 1e6, kept))
