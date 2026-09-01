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
    next_list_pages: default_parse_list 產出的後續頁碼——第 0 頁的宣稱頁
    範圍展開，加上任何有物件頁的前緣探測頁（遇空頁才收單，同一 spider
    實例跨頁共享翻頁狀態，caller 要用同一個 spider 走完整城）
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


def _enum_name(value):
    return getattr(value, 'name', str(value))


def _median_int(values):
    values = sorted(v for v in values if isinstance(v, int))
    if not values:
        return None
    return values[len(values) // 2]


def invariants(generics):
    '''分佈不變量（L3 drift 斷言用，docs/dx-roadmap.md 3-3）。

    對「解析成功的 GenericHouseItem dict」計算跨時間不該亂動的統計量：
    樓層中位數、建物型態與物件型態占比、頂加率、關鍵欄位填充率。
    斷言下在比率與中位數，永不下在特定 ID 或特定值。
    基準值來源見 baselines/README.md（2026-08-26 全量驗證產出）。
    '''
    n = len(generics)
    if n == 0:
        return {'n': 0}

    def share(pred):
        return round(sum(1 for g in generics if pred(g)) / n, 3)

    def fill(key):
        return round(sum(1 for g in generics if is_filled(g.get(key))) / n, 3)

    return {
        'n': n,
        'median_floor': _median_int(g.get('floor') for g in generics),
        'median_total_floor': _median_int(g.get('total_floor') for g in generics),
        'share_電梯大樓': share(lambda g: _enum_name(g.get('building_type')) == '電梯大樓'),
        'share_公寓': share(lambda g: _enum_name(g.get('building_type')) == '公寓'),
        'share_整層住家': share(lambda g: _enum_name(g.get('property_type')) == '整層住家'),
        'share_套房': share(
            lambda g: _enum_name(g.get('property_type')) in ('獨立套房', '分租套房')),
        'rooftop_rate': share(lambda g: g.get('is_rooftop') is True),
        'fill_rough_coordinate': fill('rough_coordinate'),
        'fill_floor_ping': fill('floor_ping'),
        'fill_monthly_price': fill('monthly_price'),
    }


def compare_invariants(current, baseline):
    '''比對 invariants() 結果與 baseline 檔（見 baselines/）。

    回傳 (results, passed, skipped_reason)：
    - results: [(名稱, 是否通過, 現值, 基準值, 容許差)]
    - 樣本數 < baseline 的 min_samples 時不做硬斷言（skipped_reason 說明），
      避免小樣本的抽樣噪音造成 nightly 誤報。
    - 所有比對皆雙向：填充率「變好」也視為漂移（例如頂加率歸零或暴增，
      都代表 591 或 parser 有變，需要人看）。
    '''
    tol = baseline.get('tolerance', {})
    tol_median = tol.get('median', 1)
    tol_share = tol.get('share', 0.10)
    tol_fill = tol.get('fill', 0.05)
    min_samples = baseline.get('min_samples', 100)

    if current.get('n', 0) < min_samples:
        return [], True, '樣本 {} < min_samples {}，跳過硬斷言'.format(
            current.get('n', 0), min_samples)

    results = []
    for key, base_value in baseline['invariants'].items():
        if key == 'n':
            continue
        cur_value = current.get(key)
        if key.startswith('median_'):
            tolerance = tol_median
        elif key.startswith('fill_'):
            tolerance = tol_fill
        else:  # share_* 與 rooftop_rate
            tolerance = tol_share
        ok = (cur_value is not None and base_value is not None
              and abs(cur_value - base_value) <= tolerance)
        results.append((key, ok, cur_value, base_value, tolerance))
    return results, all(ok for _, ok, *_ in results), None
