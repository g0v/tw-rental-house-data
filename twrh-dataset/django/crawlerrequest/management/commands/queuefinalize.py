'''1-1 收工鐵律：seeds == terminals（architecture-roadmap 軸 A）。

    done + dead == seeds，且無 pending / in_flight / failed 殘留。

go.sh／orchestrate 在 detail 收工後呼叫；紅 → 非零 exit＋Slack
（附 error 分類統計），pipeline 當場中止，不讓 sync/stats/export 把
殘缺的一輪當正常資料處理。歷次靜默失敗（403 全滅、seed 零產出、
spider「正常 finished」但少一批）都會在這裡現形，而不是事後驗屍。

紅燈條件：
  1. 零產出——當日 list 或 detail 連一顆種子都沒有
  2. 殘留——pending / in_flight / failed 未收斂
  3. dead 比率 >= 門檻（沿用 STATSCHECK_FAIL_RATIO，預設 5%）；
     低於門檻的 dead 照列訊息，不當錯誤（告警疲勞對策，同 dx 2-3）

附帶清理政策（1-1「不刪列」的容量對策）：終結列保留 N 天
（TWRH_QUEUE_RETENTION_DAYS，預設 90——開放問題 #8，實跑後定案），
窗口外批次 DELETE。何時刪不影響對帳正確性。
'''
import os
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestType, RequestStatus
from crawlerrequest.notify import send_slack
from rental import models
from rental.models import Vendor

DEFAULT_RETENTION_DAYS = int(os.environ.get('TWRH_QUEUE_RETENTION_DAYS', 90))


class Command(BaseCommand):
    help = 'Assert seeds == terminals for today\'s crawl queue; red on residue'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            '--cleanup-days', type=int, default=DEFAULT_RETENTION_DAYS,
            help='terminal rows older than N days are deleted first '
                 '(default {})'.format(DEFAULT_RETENTION_DAYS))
        parser.add_argument(
            '--no-cleanup', action='store_true',
            help='skip the rolling cleanup of old terminal rows')

    def cleanup(self, days):
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = RequestTS.objects.filter(
            status__in=(RequestStatus.DONE, RequestStatus.DEAD),
            created__lt=cutoff,
        ).delete()
        if deleted:
            print('cleanup: deleted {} terminal rows older than {} days'.format(
                deleted, days))

    def handle(self, *_args, **options):
        this_ts = {
            'year': models.current_year(),
            'month': models.current_month(),
            'day': models.current_day(),
            'hour': models.current_stepped_hour(),
        }
        date_str = '{year}/{month}/{day}'.format(**this_ts)

        if not options['no_cleanup']:
            self.cleanup(options['cleanup_days'])

        threshold = getattr(settings, 'STATSCHECK_FAIL_RATIO', 0.05)
        vendors = {v.id: v.name for v in Vendor.objects.all()}

        # (vendor, type) → {status: count}
        matrix = {}
        for row in (RequestTS.objects.filter(**this_ts)
                    .values('vendor', 'request_type', 'status')
                    .annotate(count=Count('id'))):
            key = (row['vendor'], row['request_type'])
            matrix.setdefault(key, {})[row['status']] = row['count']

        problems = []
        lines = []
        totals_by_type = {RequestType.LIST: 0, RequestType.DETAIL: 0}

        for (vendor_id, request_type), by_status in sorted(matrix.items()):
            seeds = sum(by_status.values())
            done = by_status.get(RequestStatus.DONE, 0)
            dead = by_status.get(RequestStatus.DEAD, 0)
            residue = seeds - done - dead
            totals_by_type[request_type] += seeds

            type_name = RequestType(request_type).name.lower()
            vendor_name = vendors.get(vendor_id, vendor_id)
            line = '{} {}: seeds {} = done {} + dead {} + residue {}'.format(
                vendor_name, type_name, seeds, done, dead, residue)
            lines.append(line)

            if residue > 0:
                problems.append(
                    '{} {}: {} 列未收斂（pending {} / in_flight {} / failed {}）'
                    .format(
                        vendor_name, type_name, residue,
                        by_status.get(RequestStatus.PENDING, 0),
                        by_status.get(RequestStatus.IN_FLIGHT, 0),
                        by_status.get(RequestStatus.FAILED, 0)))
            dead_ratio = dead / seeds if seeds else 0.0
            if dead_ratio >= threshold:
                problems.append(
                    '{} {}: dead 比率 {:.1%} >= 門檻 {:.0%}（{}/{}）'.format(
                        vendor_name, type_name, dead_ratio, threshold,
                        dead, seeds))

        # 零產出：list／detail 各自連一顆種子都沒有＝上游靜默陣亡
        # （實案：scrapy 2.18 不呼叫 start_requests，2026-08-28）
        for request_type, total in totals_by_type.items():
            if total == 0:
                problems.append(
                    '{}: 零種子——上游疑似靜默失敗'.format(
                        request_type.name.lower()))

        # error 分類統計（紅綠都列，紅燈時進 Slack）
        error_stats = (RequestTS.objects.filter(**this_ts)
                       .exclude(status=RequestStatus.DONE)
                       .exclude(error__isnull=True)
                       .values('error').annotate(count=Count('id'))
                       .order_by('-count')[:8])
        error_lines = [
            '  {} × {}'.format(row['count'], row['error'])
            for row in error_stats]

        for line in lines:
            print(line)
        if error_lines:
            print('error breakdown:')
            for line in error_lines:
                print(line)

        if problems:
            detail = '\n'.join('• {}'.format(p) for p in problems)
            if error_lines:
                detail += '\n*error 分類*\n' + '\n'.join(error_lines)
            send_slack(
                '*seeds != terminals* 🔴 {}\n{}'.format(date_str, detail),
                is_error=True,
                title='🧾 queue 對帳失敗 - {}'.format(date_str))
            raise CommandError(
                'seeds != terminals on {}:\n{}'.format(date_str, detail))

        print('seeds == terminals ✓ ({})'.format(date_str))
