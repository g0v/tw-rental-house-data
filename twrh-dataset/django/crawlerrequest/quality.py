'''斷言引擎（architecture-roadmap 1-2）：quality/assertions.yaml × manifest。

單一告警格式：`[stage] 斷言 id 觀測值 vs 門檻`。
動態基準＝疊窗即算（2026-09-03 拍板）：rolling 檢查當場掃近 window 份
manifest 取中位數，不物化第二種 baseline artifact；history 不足
min_history 份自動降 advisory（bootstrap 期）。
'''
import os
import statistics
from dataclasses import dataclass

import yaml

from crawlerrequest import manifests

DEFAULT_ASSERTIONS = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    '..', '..', 'quality', 'assertions.yaml')


@dataclass
class Result:
    check_id: str
    stage: str
    ok: bool
    advisory: bool
    message: str        # 「觀測值 vs 門檻」的人話版

    def line(self):
        flag = 'OK' if self.ok else ('ADVISORY' if self.advisory else 'FAIL')
        return '[{}] {} {} — {}'.format(
            self.stage, self.check_id, flag, self.message)


def load_assertions(path=None):
    with open(path or DEFAULT_ASSERTIONS) as f:
        spec = yaml.safe_load(f)
    assert spec.get('version') == 1, 'unknown assertions version'
    return spec


def history_dates(date_str, window, base_dir=None):
    '''manifest 目錄下、早於 date_str 的日期，新到舊、最多 window 份。'''
    base = base_dir or manifests.manifest_dir()
    try:
        names = os.listdir(base)
    except OSError:
        return []
    dates = sorted(
        (n for n in names if n < date_str and len(n) == 10), reverse=True)
    return dates[:window]


def rolling_values(stage, metric, date_str, window, base_dir=None):
    values = []
    for prev in history_dates(date_str, window, base_dir):
        manifest = manifests.load_manifest(prev, stage, base_dir)
        if not manifest:
            continue
        value = manifests.get_metric(manifest, metric)
        if isinstance(value, (int, float)):
            values.append(value)
    return values


def run_check(check, manifest, date_str, defaults, base_dir=None):
    check_id = check['id']
    stage = check['stage']
    metric = check['metric']
    advisory = bool(check.get('advisory'))

    def result(ok, message, force_advisory=False):
        return Result(check_id, stage, ok, advisory or force_advisory, message)

    if manifest is None:
        return result(False, 'manifest 不存在（pipeline 斷在 {} 之前?）'.format(stage))

    value = manifests.get_metric(manifest, metric)
    if value is None:
        # backfill manifest 的 queue 節等缺席項：降 advisory 並註記
        return result(
            False, 'metric {} 缺席（source={}）'.format(
                metric, manifest.get('source')),
            force_advisory=True)

    # 樣本門檻：低於 min_samples 不做硬斷言（小樣本噪音）
    if 'sample_n' in check:
        n = manifests.get_metric(manifest, check['sample_n'])
        min_samples = check.get('min_samples', defaults.get('min_samples', 0))
        if not n or n < min_samples:
            return result(
                True, '樣本 {} < {}，跳過'.format(n, min_samples))

    if 'min' in check and value < check['min']:
        return result(False, '{} = {} < min {}'.format(
            metric, value, check['min']))
    if 'max' in check and value > check['max']:
        return result(False, '{} = {} > max {}'.format(
            metric, value, check['max']))

    if 'near' in check:
        tolerance = check.get('tolerance', 0)
        if abs(value - check['near']) > tolerance:
            return result(False, '{} = {} vs 基準 {} (±{})'.format(
                metric, value, check['near'], tolerance))

    rolling_key = None
    if 'rolling_median_within' in check:
        rolling_key = 'rolling_median_within'
    elif 'rolling_median_within_abs' in check:
        rolling_key = 'rolling_median_within_abs'
    if rolling_key:
        window = check.get('window', defaults.get('window', 30))
        min_history = check.get(
            'min_history', defaults.get('min_history', 14))
        values = rolling_values(stage, metric, date_str, window, base_dir)
        if len(values) < min_history:
            return result(
                True, 'history {}/{} 份，rolling 斷言暫緩（bootstrap）'.format(
                    len(values), min_history))
        ref = statistics.median(values)
        tolerance = check[rolling_key]
        if rolling_key == 'rolling_median_within':
            diff = abs(value - ref) / ref if ref else 0.0
            desc = '相對差 {:.1%}'.format(diff)
        else:
            diff = abs(value - ref)
            desc = '絕對差 {:.3f}'.format(diff)
        if diff > tolerance:
            return result(False, '{} = {} vs 近 {} 份中位數 {}（{} > {}）'.format(
                metric, value, len(values), ref, desc, tolerance))

    return result(True, '{} = {}'.format(metric, value))


def evaluate(date_str, assertions_path=None, base_dir=None):
    spec = load_assertions(assertions_path)
    defaults = spec.get('defaults', {})
    loaded = {
        stage: manifests.load_manifest(date_str, stage, base_dir)
        for stage in manifests.BUILDERS
    }
    return [
        run_check(check, loaded.get(check['stage']), date_str,
                  defaults, base_dir)
        for check in spec.get('checks', [])
    ]
