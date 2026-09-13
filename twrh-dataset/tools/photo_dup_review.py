#!/usr/bin/env python3
'''photo_dup_review：合併 photoids（DB）與 photo_ids_from_raws（月包）的圖檔 id，建倒排索引找
「不同物件共用同一張照片」的群，出統計＋人眼審核頁（無 DB）。

    python tools/photo_dup_review.py --etc photo_ids/2026-09-14.parquet --raws photo_ids_raws.parquet --out-dir review/

輸出：
- review/components.csv     每戶一列：component_id、群大小、戶的描述欄、era、n_photos
- review/summary.txt        共用照片數分布、群大小分布、跨年群數、群內同刊登者／同價比率
- review/review.html        分層抽樣的群（2 戶／3–5 戶／6+ 戶／跨年），每群列出各戶（連到 591 頁）
                            與共用照片縮圖（591 CDN 圖檔 id 前 10 碼＝上傳 unix 秒，可還原 URL）
'''
import argparse
import collections
import csv
import datetime
import html
import itertools
import os
import random

import pyarrow.parquet as pq

THUMB = 'https://img1.591.com.tw/house/{y}/{m}/{d}/{pid}.jpg!190x150.water2.jpg'
FULL = 'https://img1.591.com.tw/house/{y}/{m}/{d}/{pid}.jpg!1000x.water2.jpg'
DESC = ['created', 'deal_status', 'monthly_price', 'floor_ping', 'floor', 'total_floor', 'property_type',
        'top_region', 'sub_region', 'rough_address', 'author_id', 'agent_org', 'contact', 'era', 'sample_url']


STATUS_NAME = {0: '待出租', 1: '已消失', 2: '已出租'}


def _enum_name(enum_cls, value):
    try:
        return enum_cls(value).name
    except (ValueError, TypeError):
        return value


def region_names():
    try:
        from scrapy_twrh.spiders import enums
        return (lambda v: _enum_name(enums.TopRegionType, v)), (lambda v: _enum_name(enums.SubRegionType, v)), \
               (lambda v: _enum_name(enums.PropertyType, v))
    except ImportError:
        ident = lambda v: v
        return ident, ident, ident


def write_photos_json(path, shared, houses, photos, sources, top):
    '''給 tools/photo_viewer.html 的資料：每張共用照片 → 對到哪些戶（重要欄位），依戶數降冪，取前 top 張。'''
    import json
    top_name, sub_name, ptype_name = region_names()
    items = sorted(shared.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:top]
    out = []
    for pid, hs in items:
        rows = []
        for h in sorted(hs):
            d = houses.get(h, {})
            c = d.get('created')
            rows.append({
                'id': h, 'created': c.date().isoformat() if hasattr(c, 'date') else None,
                'status': STATUS_NAME.get(d.get('deal_status'), d.get('deal_status')),
                'price': d.get('monthly_price'), 'ping': d.get('floor_ping'),
                'floor': d.get('floor'), 'total_floor': d.get('total_floor'),
                'ptype': ptype_name(d.get('property_type')),
                'region': '{}/{}'.format(top_name(d.get('top_region')), sub_name(d.get('sub_region'))) if d.get('top_region') is not None else None,
                'address': d.get('rough_address'), 'author': (d.get('author_id') or '')[:8] or None,
                'agent': d.get('agent_org'), 'era': '|'.join(sorted(sources.get(h, ()))),
                'n_photos': len(photos.get(h, ())),
            })
        authors = {r['author'] for r in rows if r['author']}
        prices = {r['price'] for r in rows if r['price'] is not None}
        out.append({'pid': pid, 'url': photo_url(pid, FULL), 'thumb': photo_url(pid), 'n': len(hs),
                    'same_author': len(authors) == 1 if authors else None,
                    'same_price': len(prices) == 1 if prices else None, 'houses': rows})
    with open(path, 'w') as f:
        json.dump({'generated': datetime.datetime.now().isoformat(timespec='seconds'),
                   'n_shared_photos_total': len(shared), 'photos': out}, f, ensure_ascii=False)
    return len(out)


def photo_url(pid, tmpl=THUMB):
    try:
        d = datetime.datetime.utcfromtimestamp(int(pid[:10]))
    except (ValueError, OverflowError):
        return None
    return tmpl.format(y=d.year, m='%02d' % d.month, d='%02d' % d.day, pid=pid)


def load(etc_paths, raws_paths):
    houses = {}      # hid -> desc dict
    photos = collections.defaultdict(set)   # hid -> set(pid)
    sources = collections.defaultdict(set)
    for p in etc_paths:
        t = pq.read_table(p)
        cols = {c: t[c].to_pylist() for c in t.column_names}
        for i in range(t.num_rows):
            hid = cols['vendor_house_id'][i]
            houses[hid] = {k: cols[k][i] for k in DESC if k in cols}
            if cols['photo_ids'][i]:
                photos[hid].update(cols['photo_ids'][i])
                sources[hid].add('etc:' + (cols['era'][i] or '?'))
    for p in raws_paths:
        t = pq.read_table(p, columns=['vendor_house_id', 'pack', 'photo_ids'])
        for hid, pack, ids in zip(t['vendor_house_id'].to_pylist(), t['pack'].to_pylist(), t['photo_ids'].to_pylist()):
            if ids:
                photos[hid].update(ids)
                sources[hid].add('raw:' + pack)
                houses.setdefault(hid, {})
    return houses, photos, sources


def components(photos):
    idx = collections.defaultdict(set)
    for hid, ids in photos.items():
        for pid in ids:
            idx[pid].add(hid)
    shared = {pid: hs for pid, hs in idx.items() if len(hs) >= 2}
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for hs in shared.values():
        a = next(iter(hs))
        for b in hs:
            parent[find(b)] = find(a)
    comp = collections.defaultdict(set)
    for hs in shared.values():
        for h in hs:
            comp[find(h)].add(h)
    return idx, shared, list(comp.values())


def year_of(desc):
    c = desc.get('created')
    return c.year if hasattr(c, 'year') else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--etc', nargs='*', default=[])
    ap.add_argument('--raws', nargs='*', default=[])
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--sample', type=int, default=40, help='每層抽幾群進 review.html')
    ap.add_argument('--seed', type=int, default=591)
    ap.add_argument('--top', type=int, default=20000, help='photos.json 收幾張共用最多的照片')
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    houses, photos, sources = load(args.etc, args.raws)
    idx, shared, comps = components(photos)
    comps.sort(key=lambda c: (-len(c), min(c)))
    lines = []
    n_with = len(photos)
    lines.append('houses known {} / with photos {} / photos {} / distinct {} / shared (>=2 houses) {}'.format(
        len(houses), n_with, sum(len(v) for v in photos.values()), len(idx), len(shared)))
    lines.append('photo share-count dist: ' + str(sorted(collections.Counter(min(len(v), 10) for v in shared.values()).items())))
    touched = set().union(*shared.values()) if shared else set()
    lines.append('houses sharing >=1 photo: {} ({:.1f}% of houses with photos)'.format(len(touched), 100 * len(touched) / max(n_with, 1)))
    lines.append('components: {} size dist: {}'.format(len(comps), sorted(collections.Counter(min(len(c), 20) for c in comps).items())))
    cross_year = [c for c in comps if len({year_of(houses.get(h, {})) for h in c} - {None}) >= 2]
    lines.append('components spanning >=2 created-years: {}'.format(len(cross_year)))
    # pair-level semantics where desc available
    same_author = same_price = same_region = n_pairs = 0
    for c in comps:
        for a, b in itertools.combinations(sorted(c), 2):
            da, db = houses.get(a, {}), houses.get(b, {})
            if not da.get('created') or not db.get('created'):
                continue
            n_pairs += 1
            same_author += da.get('author_id') is not None and da.get('author_id') == db.get('author_id')
            same_price += da.get('monthly_price') == db.get('monthly_price')
            same_region += (da.get('top_region'), da.get('sub_region')) == (db.get('top_region'), db.get('sub_region'))
    if n_pairs:
        lines.append('pairs with desc {}: same author {:.1f}% / same price {:.1f}% / same sub_region {:.1f}%'.format(
            n_pairs, 100 * same_author / n_pairs, 100 * same_price / n_pairs, 100 * same_region / n_pairs))
    with open(os.path.join(args.out_dir, 'summary.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))

    with open(os.path.join(args.out_dir, 'components.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['component_id', 'component_size', 'vendor_house_id', 'n_photos', 'sources'] + DESC)
        for ci, c in enumerate(comps):
            for h in sorted(c):
                d = houses.get(h, {})
                w.writerow([ci, len(c), h, len(photos[h]), '|'.join(sorted(sources[h]))] + [d.get(k) for k in DESC])

    rnd = random.Random(args.seed)
    strata = {
        '2 戶': [c for c in comps if len(c) == 2],
        '3–5 戶': [c for c in comps if 3 <= len(c) <= 5],
        '6 戶以上': [c for c in comps if len(c) >= 6],
        '跨年（首見年份不同）': cross_year,
    }
    parts = ['<meta charset="utf-8"><title>共用照片群審核</title><style>body{font-family:sans-serif;font-size:13px}'
             'table{border-collapse:collapse;margin:6px 0}td,th{border:1px solid #ccc;padding:2px 6px;vertical-align:top}'
             'img{height:90px;margin:2px}.grp{border-top:3px solid #333;margin-top:24px;padding-top:6px}</style>',
             '<h1>共用照片群審核</h1><pre>' + html.escape('\n'.join(lines)) + '</pre>']
    for name, cs in strata.items():
        pick = rnd.sample(cs, min(args.sample, len(cs)))
        parts.append('<h2>{}（共 {} 群，抽 {}）</h2>'.format(html.escape(name), len(cs), len(pick)))
        for c in pick:
            hs = sorted(c)
            shared_here = [pid for pid, v in shared.items() if len(v & c) >= 2]
            parts.append('<div class="grp"><b>群 {} 戶</b>，共用照片 {} 張<table><tr><th>物件</th><th>首見</th><th>狀態</th><th>租金</th><th>坪</th><th>樓</th><th>區</th><th>地址</th><th>刊登者</th><th>仲介</th><th>era／來源</th><th>照片數</th></tr>'.format(len(hs), len(shared_here)))
            for h in hs:
                d = houses.get(h, {})
                parts.append('<tr><td><a href="https://rent.591.com.tw/{0}" target="_blank">{0}</a></td><td>{1}</td><td>{2}</td><td>{3}</td><td>{4}</td><td>{5}/{6}</td><td>{7}/{8}</td><td>{9}</td><td>{10}</td><td>{11}</td><td>{12}</td><td>{13}</td></tr>'.format(
                    h, (d.get('created').date() if d.get('created') else ''), d.get('deal_status', ''), d.get('monthly_price', ''),
                    d.get('floor_ping', ''), d.get('floor', ''), d.get('total_floor', ''), d.get('top_region', ''), d.get('sub_region', ''),
                    html.escape(str(d.get('rough_address') or '')), html.escape(str(d.get('author_id') or '')[:8]),
                    html.escape(str(d.get('agent_org') or '')), html.escape('|'.join(sorted(sources[h]))), len(photos[h])))
            parts.append('</table><div>共用：' + ''.join(
                '<a href="{}" target="_blank"><img src="{}" title="{}"></a>'.format(photo_url(p, FULL), photo_url(p), p)
                for p in shared_here[:12] if photo_url(p)) + '</div></div>')
    with open(os.path.join(args.out_dir, 'review.html'), 'w') as f:
        f.write('\n'.join(parts))
    n_json = write_photos_json(os.path.join(args.out_dir, 'photos.json'), shared, houses, photos, sources, args.top)
    print('-> {}/review.html, components.csv, summary.txt, photos.json ({} photos; open tools/photo_viewer.html and load it)'.format(
        args.out_dir, n_json))


if __name__ == '__main__':
    main()
