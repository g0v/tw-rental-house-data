'''artifactpack：把爬取行程留在 scratch 的 shard 打成分區檔並上 S3（4a／4b）。

    manage.py artifactpack --tree list     # list/<vendor>/<date>/<run>.jsonl.zst
    manage.py artifactpack --tree parsed   # parsed/<vendor>/<date>/<run>.parquet

一輪一檔，永不改寫別輪的檔（見 rental/artifacts.py）。有 TWRH_RAW_BUCKET
即上傳（同一 bucket、同名前綴），本地分區檔保留（seed 函數／manifest 直接
讀當日目錄；EFS 上容量可忽略）。上傳失敗（打包已完成、scratch 已清）之後
用 --reupload 補：只上傳 S3 缺的 key。
'''
import os
from datetime import date as date_cls, datetime

from django.core.management.base import BaseCommand, CommandError

from rental import artifacts


class Command(BaseCommand):
    help = 'Pack list-stub / parsed shards into per-run partition files (+S3)'

    def add_arguments(self, parser):
        parser.add_argument('--tree', required=True, choices=sorted(artifacts.TREES))
        parser.add_argument('--date', help='YYYY-MM-DD（預設 TWRH_TARGET_DATE／今天）')
        parser.add_argument('--keep-scratch', action='store_true')
        parser.add_argument('--no-upload', action='store_true')
        parser.add_argument('--reupload', action='store_true',
                            help='不打包：把本地已有、S3 缺的當日分區檔補上（既有 key 不動）')

    def handle(self, *_args, **options):
        tree = options['tree']
        if options['date']:
            try:
                datetime.strptime(options['date'], '%Y-%m-%d')
            except ValueError:
                raise CommandError('--date 需為 YYYY-MM-DD')
            date_str = options['date']
        else:
            date_str = os.environ.get('TWRH_TARGET_DATE') or date_cls.today().isoformat()

        if options['reupload']:
            bucket = os.environ.get('TWRH_RAW_BUCKET')
            if not bucket:
                raise CommandError('--reupload 需要 TWRH_RAW_BUCKET')
            uploaded, skipped = artifacts.reupload_missing(bucket, tree, date_str)
            print('=== {} {} reupload: {} uploaded, {} already on S3'.format(
                tree, date_str, uploaded, skipped))
            return

        jobs = artifacts.pending_jobs(tree, date_str)
        if not jobs:
            print('no {} scratch for {}, nothing to pack'.format(tree, date_str))
            return
        bucket = None if options['no_upload'] else os.environ.get('TWRH_RAW_BUCKET')
        for (vendor, day, run), shards in sorted(jobs.items()):
            if day != date_str:
                print('=== orphan {} scratch {} {} {} (before target {}), packing too'.format(
                    tree, vendor, day, run, date_str))
            path, n_rows = artifacts.pack_run(
                tree, vendor, day, run, shards, keep_scratch=options['keep_scratch'])
            print('=== {} {} {} {}: {} shards -> {} ({} rows, {:.1f} MB)'.format(
                tree, vendor, day, run, len(shards), path, n_rows,
                os.path.getsize(path) / 1e6))
            if bucket:
                artifacts.upload(bucket, tree, vendor, day, run, path)
