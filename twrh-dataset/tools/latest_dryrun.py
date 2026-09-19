'''latest_dryrun：S3c 全戶最新狀態總表的離線重放＋校驗（無 DB、無 Django）。

    poetry run python tools/latest_dryrun.py --snapshots DIR --house DIR \
        --from 2026-09-10 --to 2026-09-17 --cutoff 2026-09-17T16:32:00+08:00 [--sample 5]

- DIR/snapshots：final snapshot parquet（<date>.parquet），從 --from 那天當起點
  （latest(from)＝snapshot(from) 本身）逐日 fold 到 --to。
- DIR/house：S2b archive 的 `public.house` parquet 分片（RDS export；時間欄是字串、
  座標是 EWKB hex／WKT 字串、JSON 欄是字串）。只比 vendor_id=1（591）且在總表裡的戶。
- --cutoff：archive 的切面時刻（RDS snapshot 取於 2026-09-17 16:32 CST）。總表用的是
  --to 那天的 **final**（含 cutoff 之後的 sweep），所以判準不是零差額，而是
  「差異戶 100% 落在 cutoff 之後被動到的戶」——每欄的 mismatch 分成 after_cutoff／before 兩桶，
  before 桶非零才是真問題（2026-09-18 拍板寫進階梯表）。

已知不可比、直接略過：author_key（DB 存 Author FK uuid，snapshot 存 item author 字串的
雜湊）、fingerprint 三欄／source／days_absent／deal_source（DB 無對應）、first_seen_at
（DB created 是入庫時刻，#11 回填的列 first_seen_at 為 NULL）。
'''
import argparse
import glob
import json
import math
import os
import struct
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import pyarrow.parquet as pq
import pyarrow.compute as pc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'django'))
from rental import latest  # noqa: E402

SAME = ['top_region', 'sub_region', 'deal_status', 'n_day_deal', 'vendor_house_url',
        'monthly_price', 'min_monthly_price', 'deposit_type', 'n_month_deposit', 'deposit',
        'is_require_management_fee', 'monthly_management_fee', 'has_parking',
        'is_require_parking_fee', 'monthly_parking_fee', 'per_ping_price', 'building_type',
        'property_type', 'is_rooftop', 'floor', 'total_floor', 'dist_to_highest_floor',
        'floor_ping', 'n_living_room', 'n_bed_room', 'n_bath_room', 'n_balcony',
        'apt_feature_code', 'rough_address', 'has_tenant_restriction', 'has_gender_restriction',
        'gender_restriction', 'can_cook', 'allow_pet', 'has_perperty_registration', 'contact',
        'agent_org']
JSON_COLS = ['additional_fee', 'living_functions', 'transportation', 'facilities', 'imgs']
TS_PAIRS = [('deal_time', 'deal_time'), ('detail_crawled_at', 'last_detail_at'),
            ('list_crawled_at', 'last_seen_at')]
HOUSE_COLS = ['vendor_id', 'vendor_house_id', 'updated', 'rough_coordinate'] + SAME + JSON_COLS \
    + [h for h, _ in TS_PAIRS]
SNAP_SKIP = {'vendor_extra'}
# 已知、可解釋的差異類（另列不計入 RESULT）：
KNOWN = {
    'facilities': 'House 被 list 日 tag 版蓋掉（2026-09-13 根因），snapshot 留 detail 版＝snapshot 對',
    'apt_feature_code': '同 facilities：list 日以 0 補陽台／衛浴位蓋掉 House 的 detail 版；snapshot 較完整',
    'floor_ping': 'House 進位到 1 位小數、snapshot 保留 2 位（exportcheck 已列為對映格式差）',
    'per_ping_price': 'floor_ping 進位差的連鎖；另有 list 改價後 House 重算而 snapshot fold 未重算（待補）',
    'imgs': 'House 存 list 的單張縮圖、parsed 2.5.0 起存 detail 整本相簿（主機／尺寸後綴已正規化）；snapshot 較完整',
}


def read_snapshot(path):
    names = [n for n in pq.read_schema(path).names if n not in SNAP_SKIP]
    return pq.read_table(path, columns=names).to_pylist()


import re
_FRAC = re.compile(r'\.(\d{1,6})(?=[+-Z]|$)')


def parse_db_ts(value):
    '''RDS export 的時間字串（`2026-09-16 18:39:13.95536+00`）→ aware UTC datetime。
    小數秒可能是 1–6 位，Python 3.10 的 fromisoformat 只吃 3 或 6 位，先補滿。'''
    if value in (None, ''):
        return None
    v = value.strip()
    if v.endswith('+00'):
        v = v + ':00'
    v = _FRAC.sub(lambda m: '.' + m.group(1).ljust(6, '0'), v)
    try:
        dt = datetime.fromisoformat(v.replace(' ', 'T'))
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def norm_ts(value):
    if value is None:
        return None
    if isinstance(value, str):
        return parse_db_ts(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return value


def parse_point(value):
    '''DB PointField 字串 → (x, y)；本專案約定 x=lat、y=lng（twrh-db-point-axis-quirk）。'''
    if value in (None, ''):
        return None
    v = value.strip()
    if v.upper().startswith('SRID=') or v.upper().startswith('POINT'):
        inner = v[v.index('(') + 1:v.index(')')]
        x, y = inner.split()
        return float(x), float(y)
    try:
        raw = bytes.fromhex(v)
    except ValueError:
        return value
    # EWKB：byte order, type(4), [srid(4)], x(8), y(8)
    order = '<' if raw[0] == 1 else '>'
    (gtype,) = struct.unpack(order + 'I', raw[1:5])
    off = 5 + (4 if gtype & 0x20000000 else 0)
    x, y = struct.unpack(order + 'dd', raw[off:off + 16])
    return x, y


_HOST = re.compile(r'^https?://[^/]+')


_SIZE = re.compile(r'!.*$')


def strip_hosts(value):
    '''591 相簿 URL：主機 img1／img2 輪替、尺寸後綴 `!510x400.jpg`（House 存 list 縮圖）vs
    `!1000x.water2.jpg`（parsed 2.5.0 起存 detail 全尺寸）——同一張圖，只比路徑主體。'''
    if isinstance(value, list):
        return [_SIZE.sub('', _HOST.sub('', v)) if isinstance(v, str) else v for v in value]
    return value


def norm_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def equal(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-6)
        except (TypeError, ValueError):
            return False
    if isinstance(a, datetime) and isinstance(b, datetime):
        # House 欄由 pipeline save 時打、stub seen_at 由 artifact sink 打，差 0.02–1.3 秒
        return abs((a - b).total_seconds()) < 5
    return a == b


def load_house(house_dir, wanted):
    files = sorted(glob.glob(os.path.join(house_dir, '*.parquet')))
    out = {}
    coord_format = Counter()
    for f in files:
        t = pq.read_table(f, columns=HOUSE_COLS)
        t = t.filter(pc.equal(t.column('vendor_id'), 1))
        mask = pc.is_in(t.column('vendor_house_id'), value_set=wanted)
        t = t.filter(mask)
        for row in t.to_pylist():
            out[row['vendor_house_id']] = row
            c = row.get('rough_coordinate')
            if c:
                coord_format['hex' if all(ch in '0123456789abcdefABCDEF' for ch in c) else c[:6]] += 1
    return files, out, coord_format


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshots', required=True)
    ap.add_argument('--house', required=True)
    ap.add_argument('--from', dest='from_date', required=True)
    ap.add_argument('--to', dest='to_date', required=True)
    ap.add_argument('--cutoff', required=True, help='archive 切面時刻（ISO，帶時區）')
    ap.add_argument('--sample', type=int, default=5)
    ap.add_argument('--write', help='把最終總表寫成 parquet 到這個路徑（體積量測用）')
    args = ap.parse_args()
    cutoff = datetime.fromisoformat(args.cutoff).astimezone(timezone.utc)

    day = datetime.strptime(args.from_date, '%Y-%m-%d').date()
    end = datetime.strptime(args.to_date, '%Y-%m-%d').date()
    table = []
    while day <= end:
        path = os.path.join(args.snapshots, day.isoformat() + '.parquet')
        if not os.path.exists(path):
            print('!!! missing snapshot {}'.format(path))
            return 2
        rows = read_snapshot(path)
        table = latest.fold(table, rows)
        by = Counter(r['deal_status'] for r in table)
        print('latest({}) = fold(prev, snapshot {} rows) -> {} rows  deal_status {}'.format(
            day, len(rows), len(table), dict(by)))
        day += timedelta(days=1)

    if args.write:
        import pyarrow as pa
        from rental import contracts
        cols = {name: [contracts.coerce_value(r.get(name), kind) for r in table]
                for name, kind in latest.LATEST_FIELDS}
        pq.write_table(pa.table(cols, schema=contracts.arrow_schema(latest.LATEST_FIELDS)),
                       args.write, compression='zstd')
        print('wrote {} ({:.1f} MB)'.format(args.write, os.path.getsize(args.write) / 1e6))

    wanted = [r['vendor_house_id'] for r in table]
    import pyarrow as pa
    files, house, coord_format = load_house(args.house, pa.array(wanted))
    print('archive house: {} parts, matched {} / {} 總表戶; coordinate formats {}'.format(
        len(files), len(house), len(table), dict(coord_format)))

    mism = defaultdict(lambda: {'after': 0, 'before': 0, 'null_in_latest': 0,
                                 'samples': [], 'null_samples': []})
    n_after = n_before = 0
    missing = []
    for row in table:
        hid = row['vendor_house_id']
        h = house.get(hid)
        if h is None:
            missing.append(hid)
            continue
        touched = max([t for t in (norm_ts(row.get('last_seen_at')), norm_ts(row.get('last_detail_at')))
                       if t is not None] or [datetime(1970, 1, 1, tzinfo=timezone.utc)])
        bucket = 'after' if touched > cutoff else 'before'
        if bucket == 'after':
            n_after += 1
        else:
            n_before += 1

        def diff(col, a, b):
            m = mism[col]
            if bucket == 'before' and b in (None, (None, None)) and a is not None:
                m['null_in_latest'] += 1     # 總表 NULL、House 有值：值缺、不是值衝突
                if len(m['null_samples']) < args.sample:
                    m['null_samples'].append((hid, a))
                return
            m[bucket] += 1
            if bucket == 'before' and len(m['samples']) < args.sample:
                m['samples'].append((hid, a, b))

        for col in SAME:
            a, b = h.get(col), row.get(col)
            if isinstance(a, str) and isinstance(b, str):
                a, b = a.strip(), b.strip()
            if not equal(a, b):
                diff(col, a, b)
        for col in JSON_COLS:
            a, b = norm_json(h.get(col)), norm_json(row.get(col))
            if col == 'imgs':
                a, b = strip_hosts(a), strip_hosts(b)
            if a != b:
                diff(col, str(a)[:60] if a is not None else None, str(b)[:60] if b is not None else None)
        for hcol, scol in TS_PAIRS:
            a, b = norm_ts(h.get(hcol)), norm_ts(row.get(scol))
            if not equal(a, b):
                diff('{}~{}'.format(hcol, scol), a, b)
        pt = parse_point(h.get('rough_coordinate'))
        lat, lng = row.get('rough_lat'), row.get('rough_lng')
        if pt is None and lat is None:
            pass
        elif pt is None or lat is None or not isinstance(pt, tuple) \
                or not (equal(pt[0], lat) and equal(pt[1], lng)):
            diff('rough_coordinate~lat/lng', pt, (lat, lng))

    print('總表 {} 戶：archive 缺 {}；cutoff 之後被動到 {}、之前 {}'.format(
        len(table), len(missing), n_after, n_before))
    if missing:
        by_hid = {r['vendor_house_id']: r for r in table}
        kinds = Counter((by_hid[h]['deal_status'], by_hid[h].get('source'),
                         by_hid[h].get('deal_source'), by_hid[h].get('monthly_price') is None)
                        for h in missing)
        print('  archive 缺的戶 (deal_status, source, deal_source, price_null) 分布:',
              kinds.most_common(6))
        print('  樣本:', [(h, by_hid[h]['date'], by_hid[h]['deal_status'], by_hid[h].get('source'))
                        for h in missing[:args.sample]])
    print('逐欄差異（欄: 值衝突 before-cutoff / 總表 NULL 而 House 有值 / after-cutoff；'
          '第一桶非零才是值衝突，第二桶是「值缺」政策題）')
    bad = nulls = known = 0
    for col, m in sorted(mism.items(), key=lambda kv: (-kv[1]['before'], -kv[1]['null_in_latest'])):
        tag = '  [已知: {}]'.format(KNOWN[col]) if col in KNOWN and m['before'] else ''
        print('  {:32} {:6} / {:6} / {:6}  {}{}'.format(
            col, m['before'], m['null_in_latest'], m['after'],
            '' if tag else (m['samples'] if m['before'] else
                            (m['null_samples'] if m['null_in_latest'] else '')), tag))
        if col in KNOWN:
            known += m['before']
        else:
            bad += m['before']
        nulls += m['null_in_latest']
    print('RESULT: {}（已知類值衝突 {} 欄次、總表 NULL 而 House 有值 {} 欄次另計）'.format(
        'AGREE' if bad == 0 else 'DIFF — before-cutoff 未解釋值衝突 {} 欄次'.format(bad), known, nulls))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
