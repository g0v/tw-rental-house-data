'''queuebusy：這張 queue 現在有沒有人在爬（flow sweep 的互斥判定，D6b）。

同一 vendor、同一日期 bucket，有「N 小時內更新過的 in_flight 列」即
busy → exit 1；否則 exit 0。以「近期更新」而非「存在 in_flight」判定，
避免被 SIGKILL 殘留的舊 in_flight 永久擋住（09-05 sweep.sh 的原設計）。
vendor 條件是 multi-vendor 前置：B 站日跑不該擋 A 站前緣掃描。

    python django/manage.py queuebusy --vendor "591 租屋網" [--hours 2] [--date YYYY-MM-DD]
'''
import os
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestStatus
from rental.models import Vendor


class Command(BaseCommand):
    help = 'exit 1 if another crawl is in flight on this vendor\'s queue today'

    def add_arguments(self, parser):
        parser.add_argument('--vendor', required=True, help='Vendor.name')
        parser.add_argument('--hours', type=float, default=2.0)
        parser.add_argument('--date', help='YYYY-MM-DD（預設 TWRH_TARGET_DATE／今天）')

    def handle(self, *_args, **options):
        override = options['date'] or os.environ.get('TWRH_TARGET_DATE')
        today = (datetime.strptime(override, '%Y-%m-%d').date() if override
                 else timezone.localtime().date())
        vendor = Vendor.objects.filter(name=options['vendor']).first()
        if vendor is None:
            raise CommandError('vendor {!r} not in DB'.format(options['vendor']))
        busy = RequestTS.objects.filter(
            year=today.year, month=today.month, day=today.day, hour=0,
            vendor=vendor, status=RequestStatus.IN_FLIGHT,
            updated__gte=timezone.now() - timedelta(hours=options['hours']),
        ).count()
        print('in_flight(<{}h) {} {}: {}'.format(
            options['hours'], options['vendor'], today, busy))
        if busy:
            raise SystemExit(1)
