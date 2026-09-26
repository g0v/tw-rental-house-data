'''queuefinalize（twrhctl 版，無 Django；由 django 同名指令搬來。只對檔案 queue，
request_ts 路徑與清理拒跑；多一個 --no-slack 給平行比對用）。

原說明：1-1 收工鐵律：seeds == terminals（architecture-roadmap 軸 A）。

    done + dead == seeds，且無 pending / in_flight / failed 殘留。

go.sh／orchestrate 在 detail 收工後呼叫；紅 → 非零 exit＋Slack
（附 error 分類統計），pipeline 當場中止，不讓 sync/stats/export 把
殘缺的一輪當正常資料處理。歷次靜默失敗（403 全滅、seed 零產出、
spider「正常 finished」但少一批）都會在這裡現形，而不是事後驗屍。

紅燈條件：
  1. 零產出——當日 list 或 detail 連一顆種子都沒有
  2. 殘留——pending / in_flight / failed 未收斂
  3. dead 比率 >= 門檻（TWRH_QUEUE_DEAD_RATIO，預設 5%；舊名 STATSCHECK_FAIL_RATIO 仍認）；
     低於門檻的 dead 照列訊息，不當錯誤（告警疲勞對策，同 dx 2-3）

附帶清理政策（1-1「不刪列」的容量對策）：終結列保留 N 天
（TWRH_QUEUE_RETENTION_DAYS，預設 90——開放問題 #8，實跑後定案），
窗口外批次 DELETE。何時刪不影響對帳正確性。
'''
import os
from datetime import timedelta

from twrhctl.base import BaseCommand, CommandError
from twrhctl import tz

from crawlerrequest.enums import RequestType, RequestStatus
from twrhctl.notify import send_slack
from rental import vendors as vendor_registry

DEFAULT_RETENTION_DAYS = int(os.environ.get('TWRH_QUEUE_RETENTION_DAYS', 90))


def default_source():
    from rental import filequeue
    return 'db' if filequeue.db_bookkeeping() else 'file'


class Command(BaseCommand):
    help = 'Assert seeds == terminals for today\'s crawl queue; red on residue'
    # 檔案時代（house 停寫、queue 不在 DB 記帳）這支指令不碰 DB；migrations check 會為了
    # 查 django_migrations 開連線，S5 之後沒有 DB 可連。還需要 ORM 時才檢查

    def add_arguments(self, parser):
        parser.add_argument(
            '--cleanup-days', type=int, default=DEFAULT_RETENTION_DAYS,
            help='terminal rows older than N days are deleted first '
                 '(default {})'.format(DEFAULT_RETENTION_DAYS))
        parser.add_argument(
            '--no-cleanup', action='store_true',
            help='skip the rolling cleanup of old terminal rows')
        parser.add_argument(
            '--source', choices=['db', 'file'],
            default=os.environ.get('TWRH_QUEUE_FINALIZE_SOURCE') or default_source(),
            help='對帳來源：只支援 file（檔案 queue）；db 需要 DB，twrhctl 拒跑')
        parser.add_argument(
            '--no-slack', action='store_true',
            help='紅燈也不發 Slack（nodjango 平行比對用，避免同一件事通知兩次）')

    def cleanup(self, days):
        from rental import filequeue
        if not filequeue.db_bookkeeping():
            # S4b 起 request_ts 沒人寫：沒有新的終結列要清，也不為此開 DB 連線（S5 後無 DB）。
            # 停寫前留下的舊列隨 RDS destroy 一起消失
            return
        raise CommandError('TWRH_QUEUE_DB=1（request_ts 清理）需要 DB，twrhctl 不支援')

    def handle(self, *_args, **options):
        target = tz.target_datetime()
        this_ts = {
            'year': target.year,
            'month': target.month,
            'day': target.day,
            'hour': target.hour - target.hour % 24,
        }
        if options['source'] != 'file':
            raise CommandError('--source db（request_ts）需要 DB，twrhctl 只支援 file')
        date_str = '{year}/{month}/{day}'.format(**this_ts)

        if not options['no_cleanup']:
            self.cleanup(options['cleanup_days'])

        threshold = float(os.environ.get('TWRH_QUEUE_DEAD_RATIO', 0.05))
        vendors = {v.id: v.name for v in vendor_registry.all(orm=False)}

        # (vendor, type) → {status: count}
        matrix = {}
        file_errors = {}
        if options['source'] == 'file':
            # S4b：檔案 queue 是唯一真相——reconcile 的 done／dead／residue 直接當狀態計數
            # （residue 記在 FAILED 位，讓下面的殘留規則與 error 分類照跑）
            from rental import filequeue
            from rental.raws import vendor_dirname
            date_iso = '{year:04d}-{month:02d}-{day:02d}'.format(**this_ts)
            max_attempts = int(os.environ.get('TWRH_QUEUE_MAX_ATTEMPTS', 3))
            for vendor in vendor_registry.all(orm=False):
                short = vendor_dirname(vendor.name)
                for type_name in filequeue.type_names(short, date_iso):
                    r = filequeue.reconcile(short, date_iso, type_name, max_attempts)
                    key = (vendor.id, RequestType[type_name.upper()])
                    matrix[key] = {RequestStatus.DONE: r['done'], RequestStatus.DEAD: r['dead'],
                                   RequestStatus.FAILED: r['residue']}
                    file_errors[key] = r['errors']

        problems = []
        lines = []
        # 零種子規則只管 list／detail：deals stage（#229）當天可以合法沒
        # 種子（stage 未排程／未上線），但有列就一樣要收斂
        totals_by_type = {RequestType.LIST: 0, RequestType.DETAIL: 0}

        for (vendor_id, request_type), by_status in sorted(matrix.items()):
            seeds = sum(by_status.values())
            done = by_status.get(RequestStatus.DONE, 0)
            dead = by_status.get(RequestStatus.DEAD, 0)
            residue = seeds - done - dead
            totals_by_type[request_type] = totals_by_type.get(request_type, 0) + seeds

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
        for request_type in (RequestType.LIST, RequestType.DETAIL):
            if totals_by_type[request_type] == 0:
                problems.append(
                    '{}: 零種子——上游疑似靜默失敗'.format(
                        request_type.name.lower()))

        # error 分類統計（紅綠都列，紅燈時進 Slack）
        if options['source'] == 'file':
            merged = {}
            for errs in file_errors.values():
                for err, n in errs.items():
                    merged[err] = merged.get(err, 0) + n
            error_lines = ['  {} × {}'.format(n, err)
                           for err, n in sorted(merged.items(), key=lambda kv: -kv[1])[:8]]

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
            if not options['no_slack']:
                send_slack(
                    '*seeds != terminals* 🔴 {}\n{}'.format(date_str, detail),
                    is_error=True,
                    title='🧾 queue 對帳失敗 - {}'.format(date_str))
            raise CommandError(
                'seeds != terminals on {}:\n{}'.format(date_str, detail))

        print('seeds == terminals ✓ ({})'.format(date_str))
