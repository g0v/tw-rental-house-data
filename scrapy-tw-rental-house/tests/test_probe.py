'''twrh probe 的斷言邏輯（離線，stub 掉抓取與解析層）。

parser 的正確性由 test_detail_raw_parser* 覆蓋；這裡只驗證 probe
把「比率 → PASS/FAIL → exit code」的判斷做對，以及 baseline 漂移比對。
'''
import json
from argparse import Namespace

import pytest

from scrapy_twrh.cli import probe


def make_args(**overrides):
    args = Namespace(
        city='金門縣', sample=20, baseline=None, delay=0,
        min_list=10, min_http=0.8, min_parse=0.9, min_field=0.8, drop=0.3)
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def detail_result(house_id, status=200, error=None, generic_extra=None):
    generic = None
    raw = None
    if status == 200 and not error:
        raw = {'price': '10,000', 'floor': '2F/5F'}
        generic = {'vendor_house_id': house_id, 'monthly_price': 10000,
                   'floor': 2, 'floor_ping': 8.5}
        if generic_extra is not None:
            generic.update(generic_extra)
    return {'house_id': house_id, 'status': status,
            'raw_attrs': raw, 'generic': generic, 'error': error}


class StubFetcher:
    def __init__(self, **_kwargs):
        pass

    def get(self, url):
        return 200, b'<html></html>'


@pytest.fixture
def stubbed(monkeypatch):
    '''回傳 dict，測試可改 list_houses 與 details 兩個 key'''
    stub = {
        'list_houses': [{'house_id': str(i), 'dict': {}} for i in range(30)],
        'details': {},  # house_id -> detail_result；缺席時給健康結果
    }
    monkeypatch.setattr(probe.http, 'Fetcher', StubFetcher)
    monkeypatch.setattr(
        probe.runner, 'parse_list_page',
        lambda spider, region, page, body: (stub['list_houses'], []))
    monkeypatch.setattr(
        probe.runner, 'parse_detail_page',
        lambda house_id, body, status=200, spider=None:
            stub['details'].get(house_id, detail_result(house_id)))
    return stub


def test_healthy_probe_passes(stubbed):
    assert probe.probe(make_args()) == 0


def test_empty_list_fails(stubbed):
    stubbed['list_houses'] = []
    assert probe.probe(make_args()) == 1


def test_tolerates_expected_404_ratio(stubbed):
    # 20 筆中 2 筆 404 —— 個別下架是預期行為，比率內要 PASS
    stubbed['details'] = {
        '0': detail_result('0', status=404),
        '1': detail_result('1', status=404),
    }
    assert probe.probe(make_args()) == 0


def test_mass_404_fails(stubbed):
    stubbed['details'] = {
        str(i): detail_result(str(i), status=404) for i in range(10)}
    assert probe.probe(make_args()) == 1


def test_legacy_template_sentinel_fails(stubbed):
    stubbed['details'] = {
        '0': detail_result('0', error='raw: LegacyTemplateError: wc-obfuscate')}
    assert probe.probe(make_args()) == 1


def test_collapsed_sentinel_field_fails(stubbed):
    # 每一筆都解得出 item，但 monthly_price 全部靜默消失
    stubbed['details'] = {
        str(i): detail_result(str(i), generic_extra={'monthly_price': None})
        for i in range(30)}
    assert probe.probe(make_args()) == 1


def test_baseline_drift_fails(stubbed, tmp_path):
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps({
        'date': '2026-08-25',
        'fill_rates': {'deposit': [95, 100], 'price': [100, 100]},
    }))
    # 現況 raw_attrs 沒有 deposit → 掉幅 95% >= 30% → FAIL
    assert probe.probe(make_args(baseline=str(baseline))) == 1


def test_baseline_within_tolerance_passes(stubbed, tmp_path):
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps({
        'fill_rates': {'price': [100, 100], 'floor': [90, 100]},
    }))
    assert probe.probe(make_args(baseline=str(baseline))) == 0


def test_load_baseline_accepts_survey_report(tmp_path):
    report = tmp_path / 'survey.json'
    report.write_text(json.dumps({
        'date': '2026-08-25',
        'detail': {'fill_rates': {'price': [10, 12]}},
    }))
    rates, date = probe.load_baseline(str(report))
    assert rates == {'price': [10, 12]}
    assert date == '2026-08-25'
