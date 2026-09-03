'''產出當日各 stage 的 manifest（architecture-roadmap 1-2）。

在 syncstateful（與 diff 模式的 synthts）之後跑，對當日資料重算
list／detail／snapshot 三份 manifest。manifest 是對資料的純函數，
同日重跑即覆蓋。品質斷言交給 qualitycheck，這裡只負責產出。

    manage.py manifest                     # 當日（吃 TWRH_TARGET_DATE）
    manage.py manifest --date 2026-09-01   # 指定日
    manage.py manifest --from 2026-09-01 --to 2026-09-10 --source backfill
                                           # 區間回補（1-3 的 9 月 backfill）
'''
import os
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError

from crawlerrequest import manifests


def _parse(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        raise CommandError('日期需為 YYYY-MM-DD: {}'.format(value))


class Command(BaseCommand):
    help = 'Build per-stage manifests for a date (or a backfill range)'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD（預設 TWRH_TARGET_DATE／今天）')
        parser.add_argument('--from', dest='date_from', help='區間起（含）')
        parser.add_argument('--to', dest='date_to', help='區間迄（含）')
        parser.add_argument(
            '--source', choices=['live', 'backfill'], default='live',
            help='backfill＝由 DB 回補歷史（queue 統計缺席，相關斷言降 advisory）')

    def handle(self, *_args, **options):
        if options['date_from'] or options['date_to']:
            if not (options['date_from'] and options['date_to']):
                raise CommandError('--from 與 --to 需成對')
            current = _parse(options['date_from'])
            end = _parse(options['date_to'])
        elif options['date']:
            current = end = _parse(options['date'])
        else:
            override = os.environ.get('TWRH_TARGET_DATE')
            current = end = _parse(override) if override else date.today()

        bucket = os.environ.get('TWRH_RAW_BUCKET')
        s3 = None
        if bucket:
            import boto3
            s3 = boto3.client('s3')

        n = 0
        while current <= end:
            for path in manifests.build_all(current, source=options['source']):
                print('wrote {}'.format(os.path.relpath(path)))
                # manifest 同步上雲（北極星 S3 樹的 manifests/ 分支）：
                # 檔案極小、日日覆蓋；3-3 的 sync-dev-data.sh 從這裡拉
                if s3 is not None:
                    key = 'manifests/{}/{}'.format(
                        current.isoformat(), os.path.basename(path))
                    s3.upload_file(path, bucket, key)
                    print('  -> s3://{}/{}'.format(bucket, key))
                n += 1
            current += timedelta(days=1)
        print('{} manifest(s) written'.format(n))
