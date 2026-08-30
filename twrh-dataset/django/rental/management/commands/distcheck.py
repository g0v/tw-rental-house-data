"""每日分佈不變量檢查——「值對不對」的防線（dx-roadmap 3-3 的當日 DB 版）。

statscheck 管量與失敗率、fill_rate extension 管欄位有沒有值；這裡管
**值的分佈**：對當天入庫的 HouseTS（OPENED）算樓層中位數、型態占比、
頂加率、關鍵欄位填充率，與 baselines/national.json 雙向比對。
防的是 591 端資料混淆（CSS order 打亂數字有前例）產出「看起來正常的錯值」
——那種錯每日量測全綠，過去要到月度出貨 gate 才會現形。

計算與比對邏輯 import 自 scrapy_twrh.cli.runner（與 twrh survey --baseline
同一套），baseline 檔為 scrapy-tw-rental-house/baselines/ 的 dataset 側副本
（image 內沒有 package repo，需自帶）。樣本數低於 min_samples 時不做硬斷言
（部分爬量的日子由 statscheck 負責告警，這裡避免小樣本噪音）。
"""
import json
import os

import requests
import sentry_sdk
from django.conf import settings
from django.core.management.base import BaseCommand
from scrapy_twrh.cli.runner import compare_invariants, invariants

from rental import enums, models
from rental.enums import DealStatusType
from rental.models import HouseTS

BASELINE_DEFAULT = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    '../../../../baselines/national.json')


def _enum_or_none(enum_cls, value):
    # DB 存 int，runner 的 share 斷言比對 enum 中文名——轉不回去（未知值）就
    # 保持原樣，計入分母、不計入任何 share
    if value is None:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return value


class Command(BaseCommand):
    help = 'Compare today\'s HouseTS distribution invariants against baseline'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument('--baseline', default=BASELINE_DEFAULT)

    def notify(self, message, is_error):
        webhook = getattr(settings, 'SLACK_WEBHOOK_URL', '')
        if not webhook:
            return
        icon = '🚨' if is_error else '✅'
        try:
            resp = requests.post(webhook, json={'blocks': [{
                'type': 'section',
                'text': {'type': 'mrkdwn',
                         'text': f'{icon} *分佈不變量檢查*\n{message}'},
            }]}, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f'Failed to send Slack notification: {e}')

    def handle(self, *_args, **options):
        ts = {
            'year': models.current_year(),
            'month': models.current_month(),
            'day': models.current_day(),
            'hour': models.current_stepped_hour(),
        }
        date_str = '{}/{}/{}'.format(ts['year'], ts['month'], ts['day'])

        rows = HouseTS.objects.filter(
            **ts, deal_status=DealStatusType.OPENED,
        ).values(
            'floor', 'total_floor', 'building_type', 'property_type',
            'is_rooftop', 'floor_ping', 'monthly_price', 'rough_coordinate',
        )
        generics = [{
            **row,
            'building_type': _enum_or_none(enums.BuildingType, row['building_type']),
            'property_type': _enum_or_none(enums.PropertyType, row['property_type']),
        } for row in rows]

        with open(options['baseline']) as f:
            baseline = json.load(f)

        current = invariants(generics)
        results, passed, skipped_reason = compare_invariants(current, baseline)

        # 每日不變量留檔（append-only jsonl）：
        # (a) 多日中位數重製 baseline 的原料——單日快照當基準會過擬合當天
        #     （fill_rough_coordinate 有時段浮動，2026-08-30 兩地實測差 4pp）；
        # (b) 未來月報「同期月 baseline」的資料基礎。
        # 落 ../logs：host＝repo logs（隨使用者同步備份）、雲上＝EFS（entrypoint
        # 接線）——baselines/ 在 image 內是 ephemeral，不能寫那裡。值可從 HouseTS
        # 回推（90 天歸檔窗口內），此檔是便利快取非唯一來源。
        history_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            '../../../../../logs/distcheck.history.jsonl')
        try:
            with open(history_path, 'a') as f:
                f.write(json.dumps({
                    'date': '{}-{:02d}-{:02d}'.format(
                        ts['year'], ts['month'], ts['day']),
                    **current,
                }, ensure_ascii=False) + '\n')
        except OSError as e:
            print(f'history append failed (non-fatal): {e}')

        if skipped_reason:
            print(f'{date_str}: distcheck skipped — {skipped_reason}')
            return

        lines = []
        for name, ok, cur, base, tol in results:
            flag = 'OK' if ok else '!! DRIFT'
            line = f'{name}: {cur} vs baseline {base} (±{tol}) {flag}'
            print(f'  {line}')
            if not ok:
                lines.append(line)

        if passed:
            print(f'{date_str}: distribution invariants OK '
                  f'({current["n"]} samples)')
            return

        error_msg = (f'{date_str}: distribution drift detected '
                     f'({current["n"]} samples): ' + '; '.join(lines))
        print(error_msg)
        sentry_sdk.capture_message(error_msg)
        self.notify(
            f'{date_str}（{current["n"]} 筆）偵測到分佈漂移：\n• '
            + '\n• '.join(lines)
            + '\n可能是 591 版式/混淆變更或 parser 回歸，請人工比對',
            is_error=True)
        raise SystemExit(1)
