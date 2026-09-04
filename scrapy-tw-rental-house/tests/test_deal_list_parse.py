'''「已成交」列表（deals stage，#229）：payload parser 與翻頁／窗口語意。

591 自 2026 改版起成交資訊只在 `list?shType=clinch`，detail 頁成交即
404。parser 只讀 Nuxt payload 的 dealDataList；DealMixin 把相對成交日
換成絕對日（基準日可注入——stage 不看時鐘），只收 lookback 窗內的事件，
整頁都比窗口舊才停止翻頁；空頁與版式不明各有一條路。
'''
from datetime import date, datetime

import pytest
import scrapy
from scrapy.http import HtmlResponse

from scrapy_twrh.items import GenericHouseItem
from scrapy_twrh.spiders import enums
from scrapy_twrh.spiders.rental591 import Rental591Spider
from scrapy_twrh.spiders.rental591.deal_list_parser import (
    UnknownDealLayoutError, parse_deal_age, parse_deal_days, parse_deal_list)
from scrapy_twrh.spiders.rental591.util import DealRequestMeta, DEAL_LIST_ENDPOINT

from .conftest import load_fixture

FIXTURE = '20260904-deal-list.html'
EMPTY_FIXTURE = '20260904-deal-list-empty.html'
REGION = {'id': '1', 'city': '台北市'}  # 需是 all_591_cities 裡的真名，start_deal 才會展開


def deal_response(body, page=1, status=200):
    meta = DealRequestMeta(REGION['id'], REGION['city'], page)
    url = '{}region={}&page={}'.format(DEAL_LIST_ENDPOINT, REGION['id'], page)
    request = scrapy.Request(url=url, meta={'rental': meta}, dont_filter=True)
    return HtmlResponse(url=url, status=status, body=body.encode('utf-8'),
                        encoding='utf-8', request=request)


def make_spider(**kwargs):
    return Rental591Spider(target_cities=[REGION['city']], **kwargs)


def run(spider, body, page=1):
    items, requests = [], []
    for entry in spider.default_parse_deal(deal_response(body, page)):
        (items if isinstance(entry, GenericHouseItem) else requests).append(entry)
    return items, requests


# --- parser ----------------------------------------------------------------

def test_parse_reads_every_item_with_variable_and_literal_values():
    items = parse_deal_list(load_fixture(FIXTURE))
    assert [i['house_id'] for i in items] == ['10000001', '10000002', '10000003']
    first = items[0]
    assert first['url'] == 'https://rent.591.com.tw/10000001'
    assert first['region_name'] == '測試市'
    assert first['kind_name'] == '獨立套房'
    assert first['title'] == '測試標題 rgb(20, 106, 153)'
    assert first['deal_total_day'] == '9天成交'
    assert first['deal_time'] == '今日'
    assert first['deal_age_days'] == 0
    assert first['n_day_deal'] == 9


def test_parse_survives_commas_and_brackets_inside_strings():
    items = parse_deal_list(load_fixture(FIXTURE))
    assert items[1]['title'] == '標題含逗號, 與 ] 括號'
    assert items[1]['price'] == '30,000'
    assert items[1]['deal_age_days'] == 1
    assert items[2]['deal_age_days'] == 3
    assert items[2]['n_day_deal'] == 1


def test_parse_empty_result_page_is_empty_list():
    assert parse_deal_list(load_fixture(EMPTY_FIXTURE)) == []


@pytest.mark.parametrize('body', [
    '<html><body>no script</body></html>',
    '<html><body><script>window.__NUXT__=(function(a){return {data:{}}}(1))</script></body></html>',
])
def test_parse_unknown_layout_raises(body):
    with pytest.raises(UnknownDealLayoutError):
        parse_deal_list(body)


@pytest.mark.parametrize('text,expected', [
    ('今日', 0), ('昨日', 1), ('前天', 2), ('4天前', 4), ('71天前', 71),
    ('2026-09-01', None), ('', None), (None, None),
])
def test_parse_deal_age(text, expected):
    assert parse_deal_age(text) == expected


@pytest.mark.parametrize('text,expected', [
    ('9天成交', 9), ('125天成交', 125), ('成交', None), (None, None),
])
def test_parse_deal_days(text, expected):
    assert parse_deal_days(text) == expected


# --- mixin: events, window, pagination --------------------------------------

def test_events_carry_absolute_deal_date_from_injected_base_date():
    spider = make_spider(deal_lookback_days=5, deal_base_date='2026-09-04')
    items, _ = run(spider, load_fixture(FIXTURE))
    assert len(items) == 3
    by_id = {i['vendor_house_id']: i for i in items}
    assert by_id['10000001']['deal_status'] == enums.DealStatusType.DEAL
    assert by_id['10000001']['deal_time'].date() == date(2026, 9, 4)
    assert by_id['10000002']['deal_time'].date() == date(2026, 9, 3)
    assert by_id['10000003']['deal_time'].date() == date(2026, 9, 1)
    assert by_id['10000001']['n_day_deal'] == 9
    assert by_id['10000001']['vendor_house_url'] == 'https://rent.591.com.tw/10000001'
    # 帶時區的 datetime：pipeline 寫 DateTimeField 不會拿到 naive 值
    assert isinstance(by_id['10000001']['deal_time'], datetime)
    assert by_id['10000001']['deal_time'].utcoffset() is not None


def test_base_date_accepts_date_objects():
    spider = make_spider(deal_lookback_days=5, deal_base_date=date(2026, 9, 10))
    items, _ = run(spider, load_fixture(FIXTURE))
    assert {i['deal_time'].date() for i in items} == {
        date(2026, 9, 10), date(2026, 9, 9), date(2026, 9, 7)}


def test_window_drops_older_events_and_stops_paging():
    # 最舊一筆是 3 天前，窗口 2 天：只收兩筆，且整頁已越過窗口→不翻下一頁
    spider = make_spider(deal_lookback_days=2, deal_base_date='2026-09-04')
    items, requests = run(spider, load_fixture(FIXTURE))
    assert [i['vendor_house_id'] for i in items] == ['10000001', '10000002']
    assert requests == []


def test_page_within_window_requests_next_page():
    spider = make_spider(deal_lookback_days=3, deal_base_date='2026-09-04')
    items, requests = run(spider, load_fixture(FIXTURE), page=4)
    assert len(items) == 3
    assert len(requests) == 1
    meta = requests[0].meta['rental']
    assert isinstance(meta, DealRequestMeta)
    assert (meta.id, meta.page) == (REGION['id'], 5)
    assert requests[0].url == '{}region=1&page=5'.format(DEAL_LIST_ENDPOINT)


def test_empty_page_ends_without_requests():
    spider = make_spider(deal_lookback_days=30, deal_base_date='2026-09-04')
    items, requests = run(spider, load_fixture(EMPTY_FIXTURE))
    assert items == [] and requests == []


def test_hard_cap_stops_runaway_paging():
    spider = make_spider(deal_lookback_days=30, deal_base_date='2026-09-04')
    _, requests = run(spider, load_fixture(FIXTURE), page=spider.DEAL_PAGE_HARD_CAP)
    assert requests == []


def test_start_deal_seeds_page_one_per_city():
    spider = make_spider()
    requests = list(spider.default_start_deal())
    assert len(requests) == 1
    assert requests[0].meta['rental'] == DealRequestMeta('1', '台北市', 1)
    assert requests[0].callback == spider.parse_deal


def test_deals_only_flag_routes_start_requests_to_deal_list():
    spider = make_spider(deals_only='True')
    requests = list(spider.start_requests())
    assert [isinstance(r.meta['rental'], DealRequestMeta) for r in requests] == [True]


def test_unknown_deal_time_is_counted_not_fatal():
    body = load_fixture(FIXTURE).replace('"3天前"', '"不明"')
    spider = make_spider(deal_lookback_days=30, deal_base_date='2026-09-04')
    items, _ = run(spider, body)
    assert [i['vendor_house_id'] for i in items] == ['10000001', '10000002']
    assert spider.deal_unknown_ages == 1
