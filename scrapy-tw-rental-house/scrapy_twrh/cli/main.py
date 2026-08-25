'''twrh — 手動測試 CLI（docs/dx-roadmap.md 2.5-4）

  twrh parse <html 檔>                離線跑 detail parser
  twrh detail <house-id 或 URL>       抓單一 detail 並解析
  twrh list <縣市名或 list URL>       抓一頁 list 並解析
  twrh survey <縣市名> [--limit N]    全量 list + detail，輸出完整性報告（不寫 DB）
  twrh harvest <縣市名> [-k N]        分層取樣 detail HTML → fixture 候選 + manifest

survey 是 L3 drift detector 的手動介面，斷言請下在比率、不要下在特定 ID。
harvest 是 1-2 的分層取樣器，分層維度 = parser 實際的分支，見 cli/harvest.py。
'''
import argparse
import json
import os
import re
import sys
import datetime
from pathlib import Path

# 必須在 import parser 前設定：CLI 不依賴任何 scrapy 專案的 settings，
# 若從 scrapy 專案目錄執行，get_project_settings() 會載入該專案設定並產生副作用
os.environ.setdefault('SCRAPY_SETTINGS_MODULE', 'scrapy_twrh.cli.null_settings')

from . import harvest as harvest_mod
from . import http, runner


def _json_default(value):
    return str(value)


def dump(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default))


def house_id_of(arg):
    match = re.search(r'(\d+)', arg)
    if not match:
        sys.exit('無法從 {!r} 解析出 house id'.format(arg))
    return match.group(1)


def cmd_parse(args):
    body = Path(args.file).read_bytes()
    result = runner.parse_detail_page(
        house_id_of(args.file) if re.search(r'\d', Path(args.file).stem) else '0',
        body, spider=runner.make_spider())
    dump(result)


def cmd_detail(args):
    fetcher = http.Fetcher(delay=args.delay)
    house_id = house_id_of(args.target)
    status, body = fetcher.get(runner.detail_url(house_id))
    result = runner.parse_detail_page(
        house_id, body, status, spider=runner.make_spider())
    dump(result)


def _resolve_region(target):
    if target.startswith('http'):
        match = re.search(r'region=(\d+)', target)
        if not match:
            sys.exit('list URL 需含 region=<id>')
        return {'id': match.group(1), 'city': 'region {}'.format(match.group(1))}
    region = runner.city_to_region(target)
    if not region:
        sys.exit('查無縣市 {!r}，請用 tw_regions 的正規名稱（如 金門縣）'.format(target))
    return region


def cmd_list(args):
    fetcher = http.Fetcher(delay=args.delay)
    region = _resolve_region(args.target)
    spider = runner.make_spider()
    status, body = fetcher.get(runner.list_url(region['id'], args.page))
    if status != 200:
        sys.exit('list 頁回應 {}'.format(status))
    houses, next_pages = runner.parse_list_page(spider, region, args.page, body)
    dump({
        'city': region['city'],
        'page': args.page,
        'total_pages': len(next_pages) + 1 if args.page == 0 else None,
        'n_houses': len(houses),
        'fill_rates': {
            k: '{}/{}'.format(*v)
            for k, v in runner.fill_rates([h['dict'] for h in houses]).items()},
        'houses': houses if args.verbose else [h['house_id'] for h in houses],
    })


def cmd_survey(args):
    fetcher = http.Fetcher(delay=args.delay)
    region = _resolve_region(args.city)
    spider = runner.make_spider()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()

    # ---- list ----
    status, body = fetcher.get(runner.list_url(region['id'], 0))
    if status != 200:
        sys.exit('list 第 1 頁就失敗（{}），中止'.format(status))
    houses, next_pages = runner.parse_list_page(spider, region, 0, body)
    list_pages_ok, list_pages_fail = 1, 0
    for page in next_pages:
        status, body = fetcher.get(runner.list_url(region['id'], page))
        if status != 200:
            list_pages_fail += 1
            continue
        page_houses, _ = runner.parse_list_page(spider, region, page, body)
        houses.extend(page_houses)
        list_pages_ok += 1
        print('[list] page {} → 累計 {} 筆'.format(page + 1, len(houses)), file=sys.stderr)

    # ---- detail ----
    targets = houses[:args.limit] if args.limit else houses
    details = []
    status_dist = {}
    for i, house in enumerate(targets):
        house_id = house['house_id']
        status, body = fetcher.get(runner.detail_url(house_id))
        status_dist[status] = status_dist.get(status, 0) + 1
        if args.save_html and status == 200:
            (out_dir / 'html').mkdir(exist_ok=True)
            (out_dir / 'html' / '{}.html'.format(house_id)).write_bytes(body)
        details.append(runner.parse_detail_page(house_id, body, status, spider=spider))
        if (i + 1) % 10 == 0:
            print('[detail] {}/{}'.format(i + 1, len(targets)), file=sys.stderr)

    ok = [d for d in details if d['status'] == 200 and d['raw_attrs']]
    raw_dicts = [d['raw_attrs'] for d in ok]
    generic_ok = [d for d in details if d['generic']]
    errors = {}
    for d in details:
        if d['error']:
            key = d['error'].split(':')[0]
            errors[key] = errors.get(key, 0) + 1

    report = {
        'city': region['city'],
        'date': today,
        'list': {
            'pages_ok': list_pages_ok,
            'pages_fail': list_pages_fail,
            'n_houses': len(houses),
            'fill_rates': runner.fill_rates([h['dict'] for h in houses]),
        },
        'detail': {
            'n_crawled': len(targets),
            'status_dist': status_dist,
            'n_raw_parsed': len(ok),
            'n_generic_parsed': len(generic_ok),
            'generic_errors': errors,
            'fill_rates': runner.fill_rates(raw_dicts),
            'property_type_dist': runner.distribution(raw_dicts, 'property_type'),
        },
        # L3 drift 斷言用的分佈不變量；任何一份 survey 報告都可回頭當新 baseline
        'invariants': runner.invariants([d['generic'] for d in generic_ok]),
    }
    report_path = out_dir / 'survey-{}-{}.json'.format(region['city'], today)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))

    # ---- summary ----
    print('\nSurvey: {} ({})'.format(region['city'], today))
    print('── list ──')
    print('  頁數 {}（失敗 {}），共 {} 筆'.format(
        list_pages_ok, list_pages_fail, len(houses)))
    print('── detail ──')
    print('  抓取 {}，status 分佈 {}'.format(len(targets), status_dist))
    print('  raw 解析成功 {}，GenericHouseItem 成功 {}，錯誤 {}'.format(
        len(ok), len(generic_ok), errors or '無'))
    print('  property_type：{}'.format(report['detail']['property_type_dist']))
    print('── detail 欄位填充率（200 且 raw 解析成功者）──')
    for key, (n, total) in report['detail']['fill_rates'].items():
        bar = '' if total == 0 else '{:4.0%}'.format(n / total)
        print('  {:24s} {:>7s} ({}/{})'.format(str(key), bar, n, total))
    print('\n報告已存：{}'.format(report_path))

    # ---- baseline 斷言（L3 drift detector 的核心）----
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text())
        results, passed, skipped = runner.compare_invariants(
            report['invariants'], baseline)
        print('\n── 不變量斷言（baseline: {}，{}）──'.format(
            baseline.get('scope', '?'), baseline.get('source', '')))
        if skipped:
            print('  SKIP：{}'.format(skipped))
            return
        for key, ok, cur, base, tolerance in results:
            print('  {:6s} {:24s} 現值 {} / 基準 {}（容許 ±{}）'.format(
                'PASS' if ok else 'FAIL', key, cur, base, tolerance))
        if not passed:
            sys.exit('不變量斷言未通過——591 或 parser 可能有變，請人工比對報告')


def cmd_harvest(args):
    fetcher = http.Fetcher(delay=args.delay)
    region = _resolve_region(args.city)
    manifest, batch_dir = harvest_mod.harvest(
        fetcher, region, args.per_stratum, Path(args.out),
        log=lambda msg: print(msg, file=sys.stderr))

    print('\nHarvest: {} ({})'.format(manifest['city'], manifest['date']))
    print('── list ──')
    print('  頁數 {}（失敗 {}），共 {} 筆'.format(
        manifest['list']['pages_ok'], manifest['list']['pages_fail'],
        manifest['list']['n_houses']))
    print('── 分層涵蓋（bucket → list 頁找到幾筆；0 = 該分層本批沒樣本）──')
    for stratum, count in manifest['coverage'].items():
        print('  {:16s} {}'.format(stratum, count))
    n_ok = sum(1 for h in manifest['houses'] if h['raw_parsed'])
    print('── 樣本 ──')
    print('  選出 {} 筆，raw 解析成功 {}，GenericHouseItem 成功 {}'.format(
        len(manifest['houses']), n_ok,
        sum(1 for h in manifest['houses'] if h['generic_parsed'])))
    print('── 填充率（樣本內，非全城 baseline 前請看 manifest）──')
    for key, (n, total) in manifest['fill_rates'].items():
        bar = '' if total == 0 else '{:4.0%}'.format(n / total)
        print('  {:24s} {:>7s} ({}/{})'.format(str(key), bar, n, total))
    print('\nfixture 候選與 manifest 已存：{}'.format(batch_dir))


def main():
    parser = argparse.ArgumentParser(prog='twrh', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--delay', type=float, default=1.0,
                        help='連續請求間隔秒數（預設 1.0）')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('parse', help='離線解析 detail HTML 檔')
    p.add_argument('file')
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser('detail', help='抓單一 detail 並解析')
    p.add_argument('target', help='house id 或 URL')
    p.set_defaults(func=cmd_detail)

    p = sub.add_parser('list', help='抓一頁 list 並解析')
    p.add_argument('target', help='縣市名或 list URL')
    p.add_argument('--page', type=int, default=0, help='0-based 頁碼')
    p.add_argument('-v', '--verbose', action='store_true')
    p.set_defaults(func=cmd_list)

    p = sub.add_parser('survey', help='全量 list+detail 完整性報告（不寫 DB）')
    p.add_argument('city', help='縣市名或 list URL')
    p.add_argument('--limit', type=int, default=0, help='detail 最多抓 N 筆（0=全部）')
    p.add_argument('--out', default='survey-output', help='報告輸出目錄')
    p.add_argument('--save-html', action='store_true', help='保存 HTML 作為 fixture 候選')
    p.add_argument('--baseline', default=None,
                   help='不變量 baseline JSON（見 baselines/），比對失敗以非零值退出')
    p.set_defaults(func=cmd_survey)

    p = sub.add_parser('harvest', help='分層取樣 detail HTML（fixture 候選，不寫 DB）')
    p.add_argument('city', help='縣市名或 list URL')
    p.add_argument('-k', '--per-stratum', type=int, default=2,
                   help='每個分層 bucket 取 N 筆（預設 2）')
    p.add_argument('--out', default='harvest-output', help='輸出目錄')
    p.set_defaults(func=cmd_harvest)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
