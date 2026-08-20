'''把現有 parser 接上假 Response 的膠水層。

只 import、不修改 parser —— selector 邏輯的單一來源仍是
list_mixin / detail_mixin / detail_raw_parser。
'''
import scrapy
from scrapy.http import HtmlResponse

from scrapy_twrh.items import RawHouseItem, GenericHouseItem
from scrapy_twrh.spiders.rental591 import util as u591
from scrapy_twrh.spiders.rental591.rental591_spider import Rental591Spider
from scrapy_twrh.spiders.rental591.detail_raw_parser import get_detail_raw_attrs
from scrapy_twrh.spiders.rental591.all_591_cities import all_591_cities


def make_spider(cities=None):
    return Rental591Spider(target_cities=cities)


def city_to_region(name):
    for city in all_591_cities:
        if city['city'] == name:
            return city
    return None


def fake_response(url, body, meta, status=200):
    request = scrapy.Request(url=url, meta=meta, dont_filter=True)
    return HtmlResponse(
        url=url, status=status, body=body, encoding='utf-8', request=request)


def list_url(region_id, page):
    '''page 為 0-based，與 ListRequestMeta 相同'''
    return '{}sort=posttime_desc&region={}&page={}'.format(
        u591.LIST_ENDPOINT, region_id, page + 1)


def detail_url(house_id):
    return '{}{}'.format(u591.DETAIL_ENDPOINT, house_id)


def parse_list_page(spider, region, page, body, status=200):
    '''回傳 (house_dicts, next_list_pages)

    house_dicts: [{house_id, dict}]，來自 RawHouseItem(is_list=True)
    next_list_pages: default_parse_list 在第 0 頁展開的後續頁碼
    '''
    meta = {'rental': u591.ListRequestMeta(region['id'], region['city'], page)}
    response = fake_response(list_url(region['id'], page), body, meta, status)

    houses = []
    next_pages = []
    for entry in spider.default_parse_list(response):
        if isinstance(entry, RawHouseItem):
            houses.append({
                'house_id': entry['house_id'],
                'dict': dict(entry.get('dict') or {}),
            })
        elif isinstance(entry, scrapy.Request):
            rental = entry.meta.get('rental')
            if isinstance(rental, u591.ListRequestMeta):
                next_pages.append(rental.page)
    return houses, next_pages


def parse_detail_page(house_id, body, status=200, spider=None):
    '''回傳 {status, raw_attrs, generic, error}

    raw_attrs: get_detail_raw_attrs 的結果（status 200 才有）
    generic:   default_parse_detail 產出的 GenericHouseItem dict（可能缺席）
    error:     generic 解析丟出的例外字串（#204 的 TypeError 會收在這）
    '''
    meta = {'rental': u591.DetailRequestMeta(house_id)}
    response = fake_response(detail_url(house_id), body, meta, status)

    ret = {'house_id': house_id, 'status': status,
           'raw_attrs': None, 'generic': None, 'error': None}

    if status == 200:
        try:
            ret['raw_attrs'] = get_detail_raw_attrs(response)
        except Exception as err:  # 回報而非中斷，survey 要統計失敗率
            ret['error'] = 'raw: {}: {}'.format(type(err).__name__, err)
            return ret

    if spider is not None:
        try:
            for entry in spider.default_parse_detail(response):
                if isinstance(entry, GenericHouseItem):
                    ret['generic'] = dict(entry)
        except Exception as err:
            ret['error'] = '{}: {}'.format(type(err).__name__, err)
    return ret


def is_filled(value):
    return value not in (None, '', [], {}, ())


def fill_rates(dicts):
    '''一群 dict 的欄位填充率：{欄位: (有值數, 總數)}，總數 = dict 個數'''
    total = len(dicts)
    counts = {}
    for one in dicts:
        for key, value in one.items():
            if is_filled(value):
                counts[key] = counts.get(key, 0) + 1
    return {key: (counts.get(key, 0), total)
            for key in sorted(set(counts) | {k for d in dicts for k in d})}


def distribution(dicts, key):
    ret = {}
    for one in dicts:
        value = one.get(key)
        if not is_filled(value):
            value = '(未解出)'
        ret[value] = ret.get(value, 0) + 1
    return dict(sorted(ret.items(), key=lambda kv: -kv[1]))
