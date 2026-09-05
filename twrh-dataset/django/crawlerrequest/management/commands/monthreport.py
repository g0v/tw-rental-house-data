"""月報產生器＋quality gate（export-automation-plan P1，出貨前的 2c＋2b）。

1-2 起改讀 manifest（architecture-roadmap：monthreport＝同一批 manifest
疊月窗）：缺爬日＝該日 detail manifest 不存在；單日失敗率＝queue 終結
統計的 (dead＋residue)/seeds。9 月由 DB 回補的 manifest（source=backfill）
沒有 queue 統計——該日失敗率未知，列 queue_unknown_days 供人工參考、
不影響紅綠（2026-09-03 拍板：該類斷言降 advisory）。

- 紅綠只由「硬事實」決定（2026-08-30 拍板）：
    缺爬日 ＞0 → 紅；單日 fail ratio > 門檻（預設 10%）→ 該日 fail，
    當月有任一 fail 日 → 紅。
- 分佈不變量（與 qualitycheck 同一組基準：quality/assertions.yaml 的
  dist.* near 值，D3 起 baselines/national.json 退場）**永遠 advisory**：
    市場有季節性，跨月比對只進報告與敘事、不決定紅綠。

用法（publish.sh 步驟 2c；手動跑亦可）：
  python django/manage.py monthreport [--month YYYYMM] [-o DIR]
      [--fail-ratio 0.1] [--baseline PATH（national.json 格式，預設由 assertions.yaml 推導）]
      [--logs-dir DIR]

exit code：0=綠、2=紅；例外才是 1。
"""
import calendar
import glob
import gzip
import json
import os
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from scrapy_twrh.cli.runner import compare_invariants, invariants

from crawlerrequest import manifests
from rental import enums
from rental.enums import DealStatusType
from rental.models import HouseTS

ASSERTIONS_DEFAULT = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    '../../../../quality/assertions.yaml')
LOGS_DEFAULT = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '../../../../../logs')


def _enum_or_none(enum_cls, value):
    if value is None:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return value


def baseline_from_assertions(path=ASSERTIONS_DEFAULT):
    '''assertions.yaml 的 detail dist.* near 值 → compare_invariants 的 baseline 形狀。

    單一基準來源（1-2 觀測層原則）：qualitycheck 日檢與月報 advisory 對同一組
    數字，baseline 重製只改 yaml。tolerance 取各類第一條的 tolerance。
    '''
    import yaml
    with open(path, encoding='utf-8') as f:
        spec = yaml.safe_load(f)
    invariants_ = {}
    tolerance = {}
    for check in spec.get('checks', []):
        metric = check.get('metric', '')
        if check.get('stage') != 'detail' or not metric.startswith('dist.') or 'near' not in check:
            continue
        name = metric[len('dist.'):]
        invariants_[name] = check['near']
        kind = ('median' if name.startswith('median_') else
                'fill' if name.startswith('fill_') else 'share')
        tolerance.setdefault(kind, check.get('tolerance', 0))
    return {
        'source': os.path.relpath(path),
        'min_samples': spec.get('defaults', {}).get('min_samples', 10000),
        'tolerance': tolerance,
        'invariants': invariants_,
    }


def _queue_fail(queue):
    '''(fail 數, seeds)；queue 統計缺席（backfill）回 None。'''
    if not queue:
        return None
    seeds = queue.get('seeds', 0)
    fail = queue.get('dead', 0) + queue.get('residue', 0)
    return fail, seeds


class Command(BaseCommand):
    help = 'Aggregate a month of manifests into a report and a red/green verdict'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            '--month', help='YYYYMM；預設 TWRH_TARGET_DATE（無則今天）的月份')
        parser.add_argument(
            '-o', '--output-dir', default='datas/publish',
            help='報告輸出目錄（default: datas/publish）')
        parser.add_argument('--fail-ratio', type=float, default=0.1)
        parser.add_argument('--baseline', default=None,
                            help='national.json 格式的基準檔；預設由 quality/assertions.yaml 推導')
        parser.add_argument(
            '--logs-dir', default=LOGS_DEFAULT,
            help='掃 breaker 事件（error_rate_exceeded）的 log 目錄；不存在則跳過')

    def handle(self, *_args, **options):
        if options['month']:
            try:
                year, month = int(options['month'][:4]), int(options['month'][4:6])
                assert 1 <= month <= 12 and len(options['month']) == 6
            except (ValueError, AssertionError):
                raise CommandError('--month 需為 YYYYMM')
        else:
            override = os.environ.get('TWRH_TARGET_DATE')
            base = (datetime.strptime(override, '%Y-%m-%d') if override
                    else timezone.localtime())
            year, month = base.year, base.month

        month_str = f'{year}{month:02d}'
        n_days = calendar.monthrange(year, month)[1]
        threshold = options['fail_ratio']

        # --- 逐日 manifest 疊月窗 ---
        days, missing_days, failed_days, queue_unknown_days = {}, [], [], []
        for day in range(1, n_days + 1):
            date_str = date(year, month, day).isoformat()
            detail = manifests.load_manifest(date_str, 'detail')
            if detail is None:
                missing_days.append(day)
                continue
            listm = manifests.load_manifest(date_str, 'list') or {}
            snapshot = manifests.load_manifest(date_str, 'snapshot') or {}

            counts = detail.get('counts', {})
            d = {
                'crawled': counts.get('n_crawled', 0),
                'new': counts.get('n_new_item', 0),
                'closed': counts.get('n_closed', 0),
                'dealt': counts.get('n_dealt', 0),
                'synthesized': snapshot.get('counts', {}).get('n_synthesized'),
                'source': detail.get('source', 'live'),
            }

            detail_fail = _queue_fail(detail.get('queue'))
            list_fail = _queue_fail((listm or {}).get('queue'))
            if detail_fail is None:
                # backfill：queue 統計已丟（舊制刪列＝完成），failure 未知
                d['fail_ratio'] = None
                queue_unknown_days.append(day)
            else:
                fail, seeds = detail_fail
                d['fail'] = fail
                d['list_fail'] = list_fail[0] if list_fail else 0
                ratio = (fail / seeds) if seeds else (1.0 if fail else 0.0)
                d['fail_ratio'] = round(ratio, 4)
                if ratio > threshold:
                    failed_days.append(day)
            days[day] = d

        # --- breaker 事件（log 掃 error_rate_exceeded，best effort）---
        breaker_events = []
        logs_dir = options['logs_dir']
        if os.path.isdir(logs_dir):
            pattern = os.path.join(logs_dir, f'{year}.{month:02d}.*')
            for path in sorted(glob.glob(pattern)):
                try:
                    opener = gzip.open if path.endswith('.gz') else open
                    with opener(path, 'rt', errors='replace') as f:
                        if any('error_rate_exceeded' in line for line in f):
                            breaker_events.append(os.path.basename(path))
                except OSError:
                    continue

        # --- 分佈不變量（advisory，不影響紅綠）---
        rows = HouseTS.objects.filter(
            year=year, month=month, deal_status=DealStatusType.OPENED,
        ).values(
            'floor', 'total_floor', 'building_type', 'property_type',
            'is_rooftop', 'floor_ping', 'monthly_price', 'rough_coordinate',
        )
        generics = [{
            **row,
            'building_type': _enum_or_none(enums.BuildingType, row['building_type']),
            'property_type': _enum_or_none(enums.PropertyType, row['property_type']),
        } for row in rows]

        if options['baseline']:
            with open(options['baseline']) as f:
                baseline = json.load(f)
            baseline_name = os.path.basename(options['baseline'])
        else:
            baseline = baseline_from_assertions()
            baseline_name = 'assertions.yaml dist.* near'
        current = invariants(generics)
        results, inv_passed, skipped_reason = compare_invariants(current, baseline)
        invariant_report = {
            'mode': 'advisory',
            'baseline': baseline_name,
            'n_samples': current.get('n', 0),
            'skipped': skipped_reason or None,
            'passed': bool(inv_passed) if not skipped_reason else None,
            'checks': [
                {'name': name, 'ok': ok, 'current': cur,
                 'baseline': base, 'tolerance': tol}
                for name, ok, cur, base, tol in results
            ],
        }

        # --- 判決：只看硬事實 ---
        reasons = []
        if missing_days:
            reasons.append(f'缺爬日 {len(missing_days)} 天: {missing_days}')
        if failed_days:
            reasons.append(
                f'fail ratio > {threshold:.0%} 的日子: {failed_days}')
        verdict = 'red' if reasons else 'green'

        report = {
            'month': month_str,
            'generated_at': timezone.localtime().isoformat(),
            'verdict': verdict,
            'reasons': reasons,
            'thresholds': {'day_fail_ratio': threshold},
            'missing_days': missing_days,
            'failed_days': failed_days,
            # queue 統計缺席的日子（backfill manifest）：失敗率未知、
            # 不影響紅綠，供人工參考
            'queue_unknown_days': queue_unknown_days,
            'days': {str(k): v for k, v in sorted(days.items())},
            'breaker_events': breaker_events,
            'invariants': invariant_report,
        }

        os.makedirs(options['output_dir'], exist_ok=True)
        out_path = os.path.join(options['output_dir'], f'{month_str}.report.json')
        with open(out_path, 'w') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        flag = '🔴 red' if verdict == 'red' else '🟢 green'
        self.stdout.write(f'[{month_str}] {flag} — {out_path}')
        for r in reasons:
            self.stdout.write(f'  - {r}')
        if queue_unknown_days:
            self.stdout.write(
                f'  queue 統計缺席（backfill）: {queue_unknown_days}')
        if invariant_report['skipped']:
            self.stdout.write(f'  invariants: skipped ({skipped_reason})')
        elif not inv_passed:
            drifts = [c['name'] for c in invariant_report['checks'] if not c['ok']]
            self.stdout.write(f'  invariants (advisory): drift in {drifts}')
        else:
            self.stdout.write('  invariants (advisory): all OK')

        raise SystemExit(0 if verdict == 'green' else 2)
