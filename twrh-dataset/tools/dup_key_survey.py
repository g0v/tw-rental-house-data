#!/usr/bin/env python
'''dup_key 量測（schema 1.0 草案 §2.7；無 DB、只讀 snapshot parquet）。

    poetry run python tools/dup_key_survey.py --snapshot-dir DIR --dates 2026-09-11 2026-09-12 2026-09-13

§2.5 定義：dup_key＝sha1(top_region, sub_region, property_type, building_type, floor,
total_floor, floor_ping 取一位小數, apt_feature_code, rough_lat／rough_lng 取四位)[:16]，
缺值以空字串參與；座標或 floor_ping 缺的列不可算、另計。

每天報：可算列數、群組大小分布、群組（≥2）內 monthly_price／author_key 全相同比率、
imgs 有交集比率。最後一天以外的每一天做「前緣重刊粗估」：當日首見新戶中，前一份
snapshot 有同 dup_key 舊戶且舊戶其後已關閉／成交的比率，再分同 author／imgs 交集／皆無。

照片鍵＝sha1(URL 去 host、去 `!…` 尺寸後綴)[:16]：591 圖檔 URL 形如
https://img{1,2}.591.com.tw/house/2020/10/25/1603635980606.jpg!510x400.jpg，同一張圖
在 list／detail 的 host 與 `!` 後綴（510x400、1000x.water2…）都會變，路徑不變。
'''
import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from urllib.parse import urlsplit

import pyarrow.parquet as pq

KEY_COLS = ('top_region', 'sub_region', 'property_type', 'building_type', 'floor',
            'total_floor', 'floor_ping', 'apt_feature_code', 'rough_lat', 'rough_lng')
LOAD_COLS = KEY_COLS + ('vendor_house_id', 'monthly_price', 'author_key', 'imgs',
                        'deal_status', 'first_seen_at')
TZ = timezone(timedelta(hours=8))


def img_key(url):
    path = urlsplit(url).path.split('!', 1)[0]
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def dup_key(row):
    if row['rough_lat'] is None or row['rough_lng'] is None or row['floor_ping'] is None:
        return None
    parts = []
    for name in KEY_COLS:
        v = row[name]
        if v is None:
            parts.append('')
        elif name == 'floor_ping':
            parts.append('{:.1f}'.format(v))
        elif name in ('rough_lat', 'rough_lng'):
            parts.append('{:.4f}'.format(v))
        else:
            parts.append(str(v))
    return hashlib.sha1('|'.join(parts).encode()).hexdigest()[:16]


def load(path):
    table = pq.read_table(path, columns=list(LOAD_COLS))
    cols = {name: table.column(name).to_pylist() for name in LOAD_COLS}
    rows = {}
    for i in range(table.num_rows):
        row = {name: cols[name][i] for name in LOAD_COLS}
        imgs = row['imgs']
        row['img_keys'] = frozenset(img_key(u) for u in json.loads(imgs)) if imgs else frozenset()
        row['dup_key'] = dup_key(row)
        rows[row['vendor_house_id']] = row
    return rows


def groups_of(rows):
    groups = defaultdict(list)
    for hid, row in rows.items():
        if row['dup_key'] is not None:
            groups[row['dup_key']].append(hid)
    return groups


def all_same(values):
    return len(values) > 0 and all(v is not None for v in values) and len(set(values)) == 1


def imgs_intersect(sets):
    sets = [s for s in sets if s]
    if len(sets) < 2:
        return False
    return len(frozenset().union(*sets)) < sum(len(s) for s in sets)


def report_day(date_str, rows, out):
    groups = groups_of(rows)
    computable = sum(len(v) for v in groups.values())
    out.append('=== {}: {} rows, {} computable ({} uncomputable: coord/floor_ping missing)'.format(
        date_str, len(rows), computable, len(rows) - computable))
    size_bucket = Counter()
    house_bucket = Counter()
    for hids in groups.values():
        n = len(hids)
        b = '1' if n == 1 else '2' if n == 2 else '3-5' if n <= 5 else '6+'
        size_bucket[b] += 1
        house_bucket[b] += n
    out.append('    group size: ' + '  '.join('{}: {} groups/{} houses'.format(
        b, size_bucket[b], house_bucket[b]) for b in ('1', '2', '3-5', '6+')))
    multi = [hids for hids in groups.values() if len(hids) >= 2]
    if multi:
        price_same = sum(all_same([rows[h]['monthly_price'] for h in hids]) for hids in multi)
        author_same = sum(all_same([rows[h]['author_key'] for h in hids]) for hids in multi)
        img_x = sum(imgs_intersect([rows[h]['img_keys'] for h in hids]) for hids in multi)
        either = sum(all_same([rows[h]['author_key'] for h in hids])
                     or imgs_intersect([rows[h]['img_keys'] for h in hids]) for hids in multi)
        biggest = max(multi, key=len)
        out.append('    groups>=2: {}  price all-same {:.1%}  author all-same {:.1%}  '
                   'imgs intersect {:.1%}  author-or-imgs {:.1%}'.format(
                       len(multi), price_same / len(multi), author_same / len(multi),
                       img_x / len(multi), either / len(multi)))
        out.append('    biggest group: {} houses (key {}), sample ids {}'.format(
            len(biggest), rows[biggest[0]]['dup_key'], biggest[:5]))
    return groups


def report_relist(prev_date, prev_rows, prev_groups, date_str, rows, later_rows, out):
    '''當日首見新戶 × 前一份 snapshot 的同 dup_key 舊戶（舊戶其後已關閉＝重刊候選）。'''
    new = [row for row in rows.values() if row['first_seen_at'] is not None
           and row['first_seen_at'].astimezone(TZ).date().isoformat() == date_str]
    computable = [row for row in new if row['dup_key'] is not None]
    with_prior = 0
    relist = Counter()
    prior_still_open = 0
    for row in computable:
        priors = [h for h in prev_groups.get(row['dup_key'], []) if h != row['vendor_house_id']]
        if not priors:
            continue
        with_prior += 1
        closed = []
        for h in priors:
            later = later_rows.get(h)
            if later is None or later['deal_status'] != 0:
                closed.append(h)
        if not closed:
            prior_still_open += 1
            continue
        if any(prev_rows[h]['author_key'] is not None
               and prev_rows[h]['author_key'] == row['author_key'] for h in closed):
            relist['same_author'] += 1
        elif any(prev_rows[h]['img_keys'] & row['img_keys'] for h in closed):
            relist['imgs_intersect'] += 1
        else:
            relist['neither'] += 1
    total_relist = sum(relist.values())
    out.append('=== relist frontier {} (new houses first seen that day vs {} snapshot; '
               'prior closed = gone or deal_status!=0 by the latest day loaded)'.format(date_str, prev_date))
    out.append('    new {} (computable {}): same-dup_key prior {}; prior closed {} ({:.1%} of computable) '
               '= same_author {} / imgs_intersect {} / neither {}; prior still open {}'.format(
                   len(new), len(computable), with_prior, total_relist,
                   total_relist / len(computable) if computable else 0,
                   relist['same_author'], relist['imgs_intersect'], relist['neither'], prior_still_open))
    strong = relist['same_author'] + relist['imgs_intersect']
    out.append('    §2.7 candidate rule (dup_key + author-or-imgs + prior closed): {} = {:.1%} of computable new'.format(
        strong, strong / len(computable) if computable else 0))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--snapshot-dir', required=True)
    ap.add_argument('--dates', nargs='+', required=True)
    args = ap.parse_args()
    out = ['dup_key survey — key cols {}; img key = sha1(path without host and !suffix)[:16]'.format(
        ', '.join(KEY_COLS))]
    days = []
    for date_str in args.dates:
        rows = load(os.path.join(args.snapshot_dir, date_str + '.parquet'))
        groups = report_day(date_str, rows, out)
        days.append((date_str, rows, groups))
    latest_rows = days[-1][1]
    for i in range(1, len(days)):
        prev_date, prev_rows, prev_groups = days[i - 1]
        report_relist(prev_date, prev_rows, prev_groups, days[i][0], days[i][1], latest_rows, out)
    print('\n'.join(out))


if __name__ == '__main__':
    main()
