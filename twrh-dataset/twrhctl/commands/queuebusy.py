'''queuebusy（twrhctl 版，無 Django；由 django 同名指令搬來。只看檔案 queue 的 worker 心跳）。

原說明：queuebusy：這張 queue 現在有沒有人在爬（flow sweep 的互斥判定，D6b）。

同一 vendor、同一日期 bucket，有「N 小時內更新過的 in_flight 列」即
busy → exit 1；否則 exit 0。以「近期更新」而非「存在 in_flight」判定，
避免被 SIGKILL 殘留的舊 in_flight 永久擋住（09-05 sweep.sh 的原設計）。
vendor 條件是 multi-vendor 前置：B 站日跑不該擋 A 站前緣掃描。

    python django/manage.py queuebusy --vendor "591 租屋網" [--hours 2] [--date YYYY-MM-DD] [--source file|db]

S4a 起（TWRH_QUEUE_SOURCE=file）沒有 in_flight 列：改看檔案 queue 的 worker 心跳
（artifacts/queue/<vendor>/<date>/<type>/active/<run>/<worker>.json 的 mtime 在窗內）；
--source 未給時跟 TWRH_QUEUE_SOURCE 走（預設 db）。
'''
import os
from datetime import datetime, timedelta

from twrhctl.base import BaseCommand, CommandError
from twrhctl import tz

from rental import filequeue
from rental import vendors as vendor_registry
from rental.raws import vendor_dirname


class Command(BaseCommand):
    help = 'exit 1 if another crawl is in flight on this vendor\'s queue today'

    def add_arguments(self, parser):
        parser.add_argument('--vendor', required=True, help='Vendor.name')
        parser.add_argument('--hours', type=float, default=2.0)
        parser.add_argument('--date', help='YYYY-MM-DD（預設 TWRH_TARGET_DATE／今天）')
        parser.add_argument('--source', choices=['file', 'db'],
                            default=os.environ.get('TWRH_QUEUE_SOURCE', 'file'))

    def handle(self, *_args, **options):
        override = options['date'] or os.environ.get('TWRH_TARGET_DATE')
        today = (datetime.strptime(override, '%Y-%m-%d').date() if override
                 else tz.localtime().date())
        try:
            vendor = vendor_registry.get(options['vendor'], orm=False)
        except LookupError:
            raise CommandError('vendor {!r} not registered'.format(options['vendor']))
        if options['source'] == 'file':
            active = filequeue.active_workers(
                vendor_dirname(vendor.name), today.isoformat(), options['hours'])
            busy = len(active)
            print('active workers(<{}h) {} {}: {}'.format(
                options['hours'], options['vendor'], today, busy))
        else:
            raise CommandError('--source db（request_ts）需要 DB，twrhctl 只支援 file')
        if busy:
            raise SystemExit(1)
