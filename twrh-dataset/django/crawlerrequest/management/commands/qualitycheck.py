'''qualitycheck：assertions.yaml × 當日 manifest ＝ 單一告警通道（1-2）。

取代（平行週後）：statscheck 的當日斷言＋Slack、fill-rate monitor 的
掉幅比對、distcheck 的分佈斷言。訊息格式統一為
`[stage] 斷言 id 觀測值 vs 門檻`，並附當日摘要。

exit code：0＝綠（advisory 不算紅）、1＝有硬斷言失敗。
go.sh 對本指令不中止 pipeline（與 statscheck 慣例一致——資料已入庫，
出不出貨是月度 gate 的事）；queue 對帳的硬中止在 queuefinalize。
'''
import os
from datetime import date, datetime

import sentry_sdk
from django.core.management.base import BaseCommand, CommandError

from crawlerrequest import manifest_files, manifests, quality
from crawlerrequest.notify import send_slack


class Command(BaseCommand):
    help = 'Assert quality/assertions.yaml against the day\'s manifests'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD（預設 TWRH_TARGET_DATE／今天）')
        parser.add_argument('--assertions', help='assertions.yaml 路徑覆寫')
        parser.add_argument(
            '--no-slack', action='store_true', help='只印結果，不發 Slack')

    def summary(self, date_str):
        '''當日摘要（綠燈訊息用；取代 statscheck 的 ✅ 日報）。'''
        detail = manifests.load_manifest(date_str, 'detail') or {}
        listm = manifests.load_manifest(date_str, 'list') or {}
        snapshot = manifests.load_manifest(date_str, 'snapshot') or {}
        counts = detail.get('counts', {})
        capture = listm.get('capture', {})
        lines = [
            '• 總爬取數: `{}`'.format(counts.get('n_crawled', '?')),
            '• 已關閉: `{}` / 已成交: `{}` / 新增: `{}`'.format(
                counts.get('n_closed', '?'), counts.get('n_dealt', '?'),
                counts.get('n_new_item', '?')),
        ]
        if capture.get('ratio') is not None:
            lines.append('• list 完整度（確認開放）: `{}/{}` (`{:.1%}`)，待確認關閉 `{}`'.format(
                capture.get('n_confirmed_open_in_list', capture.get('n_open_in_list')),
                capture.get('n_confirmed_open', capture.get('n_open')),
                capture['ratio'], capture.get('n_pending_absent', '?')))
        n_synth = snapshot.get('counts', {}).get('n_synthesized')
        if n_synth:
            lines.append('• 合成快照: `{}`'.format(n_synth))
        deals = manifests.load_manifest(date_str, 'deals') or {}
        n_events = deals.get('counts', {}).get('n_events')
        if n_events is not None:
            lines.append('• 成交事件（deals stage）: `{}`，中位 n_day_deal `{}`'.format(
                n_events, deals.get('dist', {}).get('median_n_day_deal', '?')))
        checks_line = self.checks_line(date_str)
        if checks_line:
            lines.append(checks_line)
        return '\n'.join(lines)

    def checks_line(self, date_str):
        '''雙軌 advisory 對帳（flow 記在 checks.json）：日跑 run 的三項判定一行帶出；
        非 AGREE（DIFF／crashed）標 ⚠️——這是 Phase 4 切換階梯的門檻，不能無聲。'''
        runs = manifest_files.load_checks(date_str).get('runs', {})
        run = runs.get('run', {})
        if not run:
            return None
        parts = []
        warn = False
        for name in ('seedcheck', 'filequeuecheck', 'parsedcheck',
                     'snapshotcheck-final', 'snapshotcheck'):
            verdict = run.get(name, {}).get('verdict', '—')
            if verdict != 'AGREE':
                warn = True
            parts.append('{} `{}`'.format(name, verdict))
        sweeps_off = [rid for rid, checks in runs.items() if rid != 'run'
                      and any(c.get('verdict') != 'AGREE' for c in checks.values())]
        line = '• 雙軌對帳: ' + ' / '.join(parts)
        if sweeps_off:
            line += '，sweep 非 AGREE: `{}`'.format(', '.join(sorted(sweeps_off)))
            warn = True
        return ('⚠️ ' if warn else '') + line

    def handle(self, *_args, **options):
        if options['date']:
            try:
                datetime.strptime(options['date'], '%Y-%m-%d')
            except ValueError:
                raise CommandError('--date 需為 YYYY-MM-DD')
            date_str = options['date']
        else:
            date_str = os.environ.get(
                'TWRH_TARGET_DATE') or date.today().isoformat()

        results = quality.evaluate(date_str, options['assertions'])
        for r in results:
            print(r.line())

        failures = [r for r in results if not r.ok and not r.advisory]
        advisories = [r for r in results if not r.ok and r.advisory]

        if failures:
            body = '\n'.join('• ' + r.line() for r in failures)
            if advisories:
                body += '\n*advisory*\n' + '\n'.join(
                    '• ' + r.line() for r in advisories)
            checks_line = self.checks_line(date_str)
            if checks_line:
                body += '\n' + checks_line
            body += '\n_manifests/{}/_'.format(date_str)
            print('{}: {} hard failure(s), {} advisory'.format(
                date_str, len(failures), len(advisories)))
            sentry_sdk.capture_message(
                'qualitycheck {}: {} failures'.format(date_str, len(failures)))
            if not options['no_slack']:
                send_slack(body, is_error=True,
                           title='🔴 品質斷言失敗 - {}'.format(date_str))
            raise CommandError(
                '{} hard failure(s) on {}'.format(len(failures), date_str))

        body = self.summary(date_str)
        if advisories:
            body += '\n*advisory*\n' + '\n'.join(
                '• ' + r.line() for r in advisories)
        print('{}: all assertions green ({} advisory)'.format(
            date_str, len(advisories)))
        if not options['no_slack']:
            send_slack(body, is_error=False,
                       title='📊 租屋爬蟲品質 - {}'.format(date_str))
