'''twrh probe — nightly 比率斷言（docs/dx-roadmap.md 3-2，原 3-1 併入）。

survey 回報現況、probe 下判斷：同一套 plumbing（runner + http），
但輸出是 PASS/FAIL 與 exit code，給 cron 判紅綠。

核心規則（見 roadmap Phase 3）：**只對「當下新發現的 ID 的比率」下斷言，
永不對特定 ID 或特定值下斷言**。個別 404 是預期行為（591 用 30x/404 表示
房源狀態），所以 http 斷言下在成功率、且門檻要留餘裕。

斷言清單：
  1. list 第一頁至少回 N 筆（591 沒改版、沒擋 list）
  2. detail 取樣 K 筆，HTTP 200 率 >= min-http
  3. 200 中 raw parse 成功率 >= min-parse（版式沒漂移到 parser 解不出）
  4. 舊版式（LegacyTemplateError）出現數 == 0 —— 雙向哨兵：
     出現代表 591 版式回退或恢復混淆，parser 與 OCR 決策都要重看
  5. generic 樣本中 monthly_price / floor / floor_ping 填充率 >= min-field
     （selector 漂移哨兵）
  6. （選配 --baseline）與 baseline 填充率比對，單欄位掉幅 >= drop 即 FAIL
     —— 這就是 L3 drift detector 的斷言形式，baseline 由 survey/harvest 產出
'''
import json
import sys
from pathlib import Path

from . import http, runner

SENTINEL_FIELDS = ('monthly_price', 'floor', 'floor_ping')
LEGACY_ERROR = 'LegacyTemplateError'
BASELINE_MIN_SAMPLES = 20


class Check:
    def __init__(self):
        self.results = []

    def add(self, name, ok, detail):
        self.results.append((name, ok, detail))
        print('  [{}] {} — {}'.format('PASS' if ok else 'FAIL', name, detail))

    @property
    def failed(self):
        return [name for name, ok, _ in self.results if not ok]


def load_baseline(path):
    '''接受 survey 報告（取 detail.fill_rates）或 {field: [n, total]} 純格式'''
    data = json.loads(Path(path).read_text())
    if 'detail' in data and 'fill_rates' in data['detail']:
        return data['detail']['fill_rates'], data.get('date')
    if 'fill_rates' in data:
        return data['fill_rates'], data.get('date')
    return data, None


def probe(args):
    fetcher = http.Fetcher(delay=args.delay)
    spider = runner.make_spider()
    check = Check()

    region = runner.city_to_region(args.city)
    if not region:
        sys.exit('查無縣市 {!r}，請用 tw_regions 的正規名稱（如 花蓮縣）'.format(args.city))

    print('Probe: {}（樣本 {} 筆）'.format(region['city'], args.sample))

    # ---- 1. list ----
    status, body = fetcher.get(runner.list_url(region['id'], 0))
    if status != 200:
        check.add('list 第一頁', False, 'HTTP {}'.format(status))
        return finish(check)
    houses, _ = runner.parse_list_page(spider, region, 0, body)
    check.add('list 第一頁 >= {} 筆'.format(args.min_list),
              len(houses) >= args.min_list, '{} 筆'.format(len(houses)))
    if not houses:
        return finish(check)

    # ---- 2-5. detail 取樣 ----
    targets = houses[:args.sample]
    details = []
    for house in targets:
        house_id = house['house_id']
        status, body = fetcher.get(runner.detail_url(house_id))
        details.append(
            runner.parse_detail_page(house_id, body, status, spider=spider))

    n = len(details)
    ok200 = [d for d in details if d['status'] == 200]
    raw_ok = [d for d in ok200 if d['raw_attrs']]
    legacy = [d for d in details if d['error'] and LEGACY_ERROR in d['error']]

    check.add('detail HTTP 200 率 >= {:.0%}'.format(args.min_http),
              len(ok200) / n >= args.min_http,
              '{}/{}（404 屬預期，比率斷言）'.format(len(ok200), n))
    if ok200:
        check.add('raw parse 成功率 >= {:.0%}'.format(args.min_parse),
                  len(raw_ok) / len(ok200) >= args.min_parse,
                  '{}/{}'.format(len(raw_ok), len(ok200)))
    check.add('舊版式哨兵 == 0', not legacy,
              '{} 筆 {}'.format(len(legacy), LEGACY_ERROR) if legacy else '未出現')

    generic_dicts = [d['generic'] for d in details if d['generic']]
    if generic_dicts:
        rates = runner.fill_rates(generic_dicts)
        for field in SENTINEL_FIELDS:
            filled, total = rates.get(field, (0, len(generic_dicts)))
            check.add('{} 填充率 >= {:.0%}'.format(field, args.min_field),
                      total > 0 and filled / total >= args.min_field,
                      '{}/{}'.format(filled, total))
    else:
        check.add('GenericHouseItem 產出', False, '0/{} —— parser 全滅？'.format(n))

    # ---- 6. baseline drift ----
    if args.baseline:
        baseline, base_date = load_baseline(args.baseline)
        current = runner.fill_rates([d['raw_attrs'] for d in raw_ok])
        drifted = []
        for field, value in baseline.items():
            base_n, base_total = value
            if base_total < BASELINE_MIN_SAMPLES:
                continue
            cur_n, cur_total = current.get(field, (0, len(raw_ok)))
            if not cur_total:
                continue
            drop = base_n / base_total - cur_n / cur_total
            if drop >= args.drop:
                drifted.append('{} {:.0%}→{:.0%}'.format(
                    field, base_n / base_total, cur_n / cur_total))
        check.add(
            'baseline 漂移（掉幅 >= {:.0%}）'.format(args.drop), not drifted,
            '；'.join(drifted) if drifted
            else '無（baseline {}）'.format(base_date or Path(args.baseline).name))

    return finish(check)


def finish(check):
    failed = check.failed
    if failed:
        print('\nFAIL：{}'.format('、'.join(failed)))
        return 1
    print('\nPASS')
    return 0


def cmd_probe(args):
    sys.exit(probe(args))


def register(sub):
    p = sub.add_parser('probe', help='nightly 比率斷言（survey plumbing + exit code）')
    p.add_argument('city', help='縣市名（tw_regions 正規名稱）')
    p.add_argument('-k', '--sample', type=int, default=20, help='detail 取樣數（預設 20）')
    p.add_argument('--baseline', help='survey 報告或 {field: [n,total]} JSON，做填充率漂移比對')
    p.add_argument('--min-list', type=int, default=10, help='list 第一頁最少筆數（預設 10）')
    p.add_argument('--min-http', type=float, default=0.8, help='detail 200 率門檻（預設 0.8）')
    p.add_argument('--min-parse', type=float, default=0.9, help='raw parse 成功率門檻（預設 0.9）')
    p.add_argument('--min-field', type=float, default=0.8, help='哨兵欄位填充率門檻（預設 0.8）')
    p.add_argument('--drop', type=float, default=0.3, help='baseline 漂移告警掉幅（預設 0.3）')
    p.set_defaults(func=cmd_probe)
