'''分層取樣器（docs/dx-roadmap.md 1-2）。

從 list 頁分層取樣，抓 detail 存成 fixture 候選，並附 manifest 與填充率報告
（1-5 baseline 與 L3 drift detector 都以此為輸入）。不寫 DB。

分層維度由 parser 實際的分支決定，不是憑感覺（見 roadmap Phase 1 表）：
- property_type：車位／整層住家／其他（三類走不同的 item_list 解析）
- contact：屋主／仲介／代理人（依字串前綴分支）
- 價格區間：price 含 `~`（社會住宅，#87 的 min_monthly_price 分支）
- floor 字串：頂加／B1／整棟／樓層區間／一般（各自分支）

已下架／已成交頁無法從 list 分層取得，仍需手動補（fixtures/README.md 的 gap）。

list 頁本身已帶 property_type 與 contact_info，所以分層只花 list 頁的成本；
detail 只抓被選進樣本的物件。
'''
import datetime
import json
import sys
from pathlib import Path

from . import runner

# 已知的分層全集：coverage 要顯性列出 0 筆的 bucket，沒取到樣的分層不能靜默消失
KNOWN_STRATA = [
    ('property', '車位'), ('property', '整層住家'), ('property', '其他'),
    ('contact', '屋主'), ('contact', '仲介'), ('contact', '代理人'),
    ('price', '價格區間'),
    ('floor', '頂加'), ('floor', 'B1'), ('floor', '整棟'),
    ('floor', '樓層區間'), ('floor', '一般'),
]

# (維度, 值) 取自 list 頁 raw dict；一間房可同時落在多個 bucket
def classify(list_dict):
    strata = []

    property_type = list_dict.get('property_type')
    if property_type == '車位':
        strata.append(('property', '車位'))
    elif property_type == '整層住家':
        strata.append(('property', '整層住家'))
    elif property_type:
        strata.append(('property', '其他'))

    contact = list_dict.get('contact_info', '')
    for role in ('屋主', '仲介', '代理人'):
        if role in contact:
            strata.append(('contact', role))
            break

    if '~' in list_dict.get('price', ''):
        strata.append(('price', '價格區間'))

    floor = list_dict.get('floor', '')
    if floor:
        head = floor.split('/')[0]
        if '加蓋' in head:
            strata.append(('floor', '頂加'))
        elif 'B' in head:
            strata.append(('floor', 'B1'))
        elif '整棟' in head:
            strata.append(('floor', '整棟'))
        elif '~' in head:
            strata.append(('floor', '樓層區間'))
        else:
            strata.append(('floor', '一般'))

    return strata


def pick_sample(houses, per_stratum):
    '''每個 bucket 取 K 筆；稀有 bucket 先選，一間房可同時涵蓋多個 bucket。

    回傳 (selected, coverage)：
    selected: {house_id: {'house': house, 'strata': [...]}}
    coverage: {'維度/值': 找到幾筆}（含 0 筆的顯性回報，不靜默）
    '''
    buckets = {}
    strata_of = {}
    for house in houses:
        strata = classify(house['dict'])
        strata_of[house['house_id']] = strata
        for stratum in strata:
            buckets.setdefault(stratum, []).append(house)

    selected = {}
    # 稀有 bucket 先選，比較不會被大 bucket 先佔掉名額
    for stratum in sorted(buckets, key=lambda s: len(buckets[s])):
        # 已選進樣本的房若涵蓋此 bucket，先抵扣名額
        quota = per_stratum - sum(
            1 for house_id in selected if stratum in strata_of[house_id])
        for house in buckets[stratum]:
            if quota <= 0:
                break
            if house['house_id'] in selected:
                continue
            selected[house['house_id']] = {
                'house': house,
                'strata': strata_of[house['house_id']],
            }
            quota -= 1

    coverage = {
        '{}/{}'.format(*stratum): len(buckets.get(stratum, []))
        for stratum in KNOWN_STRATA
    }
    # classify 之後新增的值也要看得見
    for stratum in sorted(buckets):
        coverage.setdefault('{}/{}'.format(*stratum), len(buckets[stratum]))
    return selected, coverage


def crawl_lists(fetcher, region, spider, log=lambda *_: None):
    '''全部 list 頁 → (houses, n_pages_ok, n_pages_fail)'''
    status, body = fetcher.get(runner.list_url(region['id'], 0))
    if status != 200:
        sys.exit('list 第 1 頁就失敗（{}），中止'.format(status))
    houses, next_pages = runner.parse_list_page(spider, region, 0, body)
    pages_ok, pages_fail = 1, 0
    for page in next_pages:
        status, body = fetcher.get(runner.list_url(region['id'], page))
        if status != 200:
            pages_fail += 1
            continue
        page_houses, _ = runner.parse_list_page(spider, region, page, body)
        houses.extend(page_houses)
        pages_ok += 1
        log('[list] page {} → 累計 {} 筆'.format(page + 1, len(houses)))
    return houses, pages_ok, pages_fail


def harvest(fetcher, region, per_stratum, out_dir, log=lambda *_: None):
    '''取樣 → 抓 detail → 存 HTML + manifest。回傳 manifest dict。'''
    spider = runner.make_spider()
    today = datetime.date.today().isoformat()

    houses, pages_ok, pages_fail = crawl_lists(fetcher, region, spider, log)
    selected, coverage = pick_sample(houses, per_stratum)
    log('[sample] {} 個 bucket，選出 {} 筆'.format(len(coverage), len(selected)))

    batch_dir = out_dir / '{}-{}'.format(region['city'], today)
    (batch_dir / 'html').mkdir(parents=True, exist_ok=True)

    entries = []
    raw_dicts = []
    for house_id, info in sorted(selected.items()):
        status, body = fetcher.get(runner.detail_url(house_id))
        entry = {
            'house_id': house_id,
            'strata': ['{}/{}'.format(*s) for s in info['strata']],
            'status': status,
            'file': None,
            'raw_parsed': False,
            'generic_parsed': False,
            'error': None,
        }
        if status == 200:
            path = batch_dir / 'html' / '{}.html'.format(house_id)
            path.write_bytes(body)
            entry['file'] = str(path.relative_to(batch_dir))
            result = runner.parse_detail_page(house_id, body, status, spider=spider)
            entry['raw_parsed'] = bool(result['raw_attrs'])
            entry['generic_parsed'] = bool(result['generic'])
            entry['error'] = result['error']
            if result['raw_attrs']:
                raw_dicts.append(result['raw_attrs'])
        entries.append(entry)
        log('[detail] {} {} {}'.format(house_id, status, entry['strata']))

    manifest = {
        'city': region['city'],
        'date': today,
        'per_stratum': per_stratum,
        'list': {
            'pages_ok': pages_ok,
            'pages_fail': pages_fail,
            'n_houses': len(houses),
        },
        # 含 0 筆的 bucket 也列出來：沒取到樣的分層要看得見，不能靜默
        'coverage': coverage,
        'houses': entries,
        # 1-5 baseline：本批 detail raw dict 的欄位填充率
        'fill_rates': {
            key: list(value)
            for key, value in runner.fill_rates(raw_dicts).items()
        },
    }
    (batch_dir / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return manifest, batch_dir
