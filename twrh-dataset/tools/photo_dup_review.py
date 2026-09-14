#!/usr/bin/env python3
'''photo_dup_review：合併 photoids（DB）與 photo_ids_from_raws（月包）的圖檔 id，建倒排索引找
「不同物件共用同一張照片」的群，出統計＋人眼審核頁（無 DB）。

    python tools/photo_dup_review.py --etc photo_ids/2026-09-14.parquet --raws photo_ids_raws.parquet --out-dir review/
    # 全量（850 萬戶）在雲上：TWRH_RUN_CPU=4096 TWRH_RUN_MEMORY=16384 run-cloud … --etc s3 同步下來的 parquet --upload s3://…/
    # 重活在 Arrow（攤平、去重、每張照片戶數），只有被共用的照片與牽涉的戶進 Python

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
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

THUMB = 'https://img1.591.com.tw/house/{y}/{m}/{d}/{pid}.jpg!190x150.water2.jpg'
FULL = 'https://img1.591.com.tw/house/{y}/{m}/{d}/{pid}.jpg!1000x.water2.jpg'
DESC = ['created', 'deal_status', 'monthly_price', 'floor_ping', 'floor', 'total_floor', 'property_type',
        'top_region', 'sub_region', 'rough_address', 'author_id', 'agent_org', 'contact', 'era', 'sample_url']


STATUS_NAME = {0: '待出租', 1: '已消失', 2: '已出租'}


def log(msg):
    '''階段進度：帶時間戳＋flush（雲上 stdout 給 awslogs 是 block-buffered，沒 flush 整段跑完前看不到任何字）。'''
    print('[{}] {}'.format(datetime.datetime.now().strftime('%H:%M:%S'), msg), flush=True)


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


def write_photos_json(path, shared, houses, photos, sources, top, comp_of=None, gstats=None, house_shared=None,
                      max_houses=200):
    '''給 tools/photo_viewer.html 的資料：每張共用照片 → 對到哪些戶（重要欄位），依戶數降冪，取前 top 張；
    每張最多列 max_houses 戶（n 仍是全數；萬用圖一張連幾萬戶，全列 json 會爆）。'''
    import json
    top_name, sub_name, ptype_name = region_names()
    items = sorted(shared.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:top]
    out = []
    for pid, hs in items:
        rows = []
        for h in sorted(hs)[:max_houses]:
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
                'n_shared': (house_shared or {}).get(h),
            })
        authors = {r['author'] for r in rows if r['author']}
        prices = {r['price'] for r in rows if r['price'] is not None}
        g = gstats[comp_of[next(iter(hs))]] if comp_of and gstats else None
        out.append({'pid': pid, 'url': photo_url(pid, FULL), 'thumb': photo_url(pid), 'n': len(hs),
                    'same_author': len(authors) == 1 if authors else None,
                    'same_price': len(prices) == 1 if prices else None,
                    'group': g, 'houses': rows})
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


def _pairs(path, id_col, src_prefix, src_col):
    '''parquet（一戶一列、photo_ids 是 list）→ Arrow (hid, pid, src) 攤平表。'''
    t = pq.read_table(path, columns=[id_col, 'photo_ids', src_col])
    ids = t.column('photo_ids')
    parent = pc.list_parent_indices(ids)
    src = pc.binary_join_element_wise(
        pa.scalar(src_prefix), pc.fill_null(t.column(src_col).cast(pa.string()), '?'), '')
    return pa.table({
        'hid': t.column(id_col).cast(pa.string()).take(parent),
        'pid': pc.list_flatten(ids).cast(pa.string()),
        'src': src.take(parent),
    })


def build(etc_paths, raws_paths):
    '''全量規模（850 萬戶／3,800 萬張）的作法：攤平成 (hid, pid) 對後全在 Arrow 裡去重、算每張照片的戶數，
    只把「被 ≥2 戶共用」的照片與牽涉到的戶拿進 Python（union-find、描述欄、每戶照片集合）。
    回傳 houses／photos／sources 只含群內的戶；counts 給 summary 的全量數字。'''
    tables = [_pairs(p, 'vendor_house_id', 'etc:', 'era') for p in etc_paths]
    tables += [_pairs(p, 'vendor_house_id', 'raw:', 'pack') for p in raws_paths]
    pairs = pa.concat_tables(tables)
    del tables
    log('flattened pairs {}'.format(pairs.num_rows))
    uniq = pairs.group_by(['hid', 'pid']).aggregate([])                       # 去重後的 (hid, pid)
    counts = {'pairs': uniq.num_rows,
              'houses_with_photos': pc.count_distinct(uniq.column('hid')).as_py(),
              'distinct_photos': pc.count_distinct(uniq.column('pid')).as_py()}
    per_pid = uniq.group_by('pid').aggregate([('hid', 'count')])
    shared_pids = per_pid.filter(pc.greater_equal(per_pid.column('hid_count'), 2)).column('pid')
    del per_pid
    shared_pairs = uniq.filter(pc.is_in(uniq.column('pid'), value_set=shared_pids))
    log('pairs {} / shared photos {} / shared pairs {}'.format(
        counts['pairs'], len(shared_pids), shared_pairs.num_rows))

    # union-find：只走共用照片的 (pid → 戶) 邊
    shared = collections.defaultdict(set)
    for hid, pid in zip(shared_pairs.column('hid').to_pylist(), shared_pairs.column('pid').to_pylist()):
        shared[pid].add(hid)
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
    comps = list(comp.values())
    in_group = pa.array(list(parent), type=pa.string())
    log('houses in groups {} / groups {} / largest {}'.format(
        len(parent), len(comps), sorted((len(c) for c in comps), reverse=True)[:10]))

    # 群內戶的完整照片集合與來源（含它們不共用的照片，算「相異張數」用）
    photos = collections.defaultdict(set)
    mine = uniq.filter(pc.is_in(uniq.column('hid'), value_set=in_group))
    for hid, pid in zip(mine.column('hid').to_pylist(), mine.column('pid').to_pylist()):
        photos[hid].add(pid)
    del uniq, mine
    log('per-house photo sets built')
    sources = collections.defaultdict(set)
    src = pairs.filter(pc.is_in(pairs.column('hid'), value_set=in_group)).group_by(['hid', 'src']).aggregate([])
    for hid, s in zip(src.column('hid').to_pylist(), src.column('src').to_pylist()):
        sources[hid].add(s)
    del pairs, src
    log('per-house sources built')
    houses = {}
    for p in etc_paths:
        t = pq.read_table(p, columns=['vendor_house_id'] + [c for c in DESC if c not in ('era', 'sample_url')]
                          + ['era', 'sample_url'])
        counts['houses_known'] = counts.get('houses_known', 0) + t.num_rows
        t = t.filter(pc.is_in(t.column('vendor_house_id'), value_set=in_group))
        for row in t.to_pylist():
            houses[row['vendor_house_id']] = {k: row.get(k) for k in DESC}
    for h in parent:
        houses.setdefault(h, {})
    log('house descriptions loaded {}'.format(len(houses)))
    return houses, photos, sources, dict(shared), comps, counts


def group_photo_stats(comps, photos):
    '''每群：共用張數（群內 ≥2 戶都有的照片）、相異張數、每戶「與群內他戶重複的張數」。
    回傳 (house→群序號, [每群 dict], house→n_shared)。'''
    of, stats, house_shared = {}, [], {}
    for ci, c in enumerate(comps):
        cnt = collections.Counter()
        for h in c:
            of[h] = ci
            cnt.update(photos[h])
        shared_here = {pid for pid, n in cnt.items() if n >= 2}
        for h in c:
            house_shared[h] = len(photos[h] & shared_here)
        stats.append({'id': ci, 'size': len(c), 'shared_photos': len(shared_here), 'distinct_photos': len(cnt),
                      'max_house_photos': max(len(photos[h]) for h in c)})
    return of, stats, house_shared


def group_shared_photos(c, photos):
    '''群內 ≥2 戶都有的照片（依共用戶數降冪）。只看群內各戶的照片集合，不掃全域 7 百萬張 shared。'''
    cnt = collections.Counter()
    for h in c:
        cnt.update(photos[h])
    return [pid for pid, n in cnt.most_common() if n >= 2]


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
    ap.add_argument('--max-pairs', type=int, default=1000,
                    help='成對語意統計每群最多抽幾對（全配對是 O(n²)，一張萬用圖連出的萬戶大群跑不完）')
    ap.add_argument('--rows', type=int, default=30, help='review.html 每群最多列幾戶')
    ap.add_argument('--json-houses', type=int, default=200, help='photos.json 每張照片最多列幾戶（n 仍是全數）')
    ap.add_argument('--upload', help='跑完把 out-dir 四個檔上到這個 S3 前綴（s3://bucket/prefix/）')
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    houses, photos, sources, shared, comps, counts = build(args.etc, args.raws)
    comps.sort(key=lambda c: (-len(c), min(c)))
    rnd = random.Random(args.seed)
    lines = []
    lines.append('largest components (houses): {}'.format([len(c) for c in comps[:10]]))
    n_with = counts['houses_with_photos']
    lines.append('houses known {} / with photos {} / photos {} / distinct {} / shared (>=2 houses) {}'.format(
        counts.get('houses_known', 0), n_with, counts['pairs'], counts['distinct_photos'], len(shared)))
    lines.append('photo share-count dist: ' + str(sorted(collections.Counter(min(len(v), 10) for v in shared.values()).items())))
    touched = set().union(*shared.values()) if shared else set()
    lines.append('houses sharing >=1 photo: {} ({:.1f}% of houses with photos)'.format(len(touched), 100 * len(touched) / max(n_with, 1)))
    lines.append('components: {} size dist: {}'.format(len(comps), sorted(collections.Counter(min(len(c), 20) for c in comps).items())))
    cross_year = [c for c in comps if len({year_of(houses.get(h, {})) for h in c} - {None}) >= 2]
    lines.append('components spanning >=2 created-years: {}'.format(len(cross_year)))
    log('summary: distributions done')
    comp_of, gstats, house_shared = group_photo_stats(comps, photos)
    log('group photo stats done')
    bucket = lambda n: '1' if n == 1 else '2' if n == 2 else '3-5' if n <= 5 else '6-10' if n <= 10 else '11+'
    lines.append('shared photos per group: ' + str(sorted(collections.Counter(bucket(g['shared_photos']) for g in gstats).items(),
                                                          key=lambda kv: ['1', '2', '3-5', '6-10', '11+'].index(kv[0]))))
    two = [g for g in gstats if g['size'] == 2]
    if two:
        full = sum(1 for g in two if g['shared_photos'] == g['distinct_photos'])
        one = sum(1 for g in two if g['shared_photos'] == 1 and g['distinct_photos'] > 1)   # 只重一張、其餘不同
        lines.append('2-house groups {}: share only 1 of several photos {} ({:.1f}%), share every photo (identical album) {} ({:.1f}%)'.format(
            len(two), one, 100 * one / len(two), full, 100 * full / len(two)))
    lines.append('houses in groups: shared/own photos ratio dist: ' + str(sorted(collections.Counter(
        'all' if house_shared[h] == len(photos[h]) else '>=half' if house_shared[h] * 2 >= len(photos[h]) else '<half'
        for h in comp_of).items())))
    # pair-level semantics where desc available；每群最多 max_pairs 對（全配對是 O(n²)）
    same_author = same_price = same_region = n_pairs = n_capped = 0
    for c in comps:
        hs = sorted(c)
        if len(hs) * (len(hs) - 1) // 2 > args.max_pairs:
            n_capped += 1
            pairs_iter = (rnd.sample(hs, 2) for _ in range(args.max_pairs))
        else:
            pairs_iter = itertools.combinations(hs, 2)
        for a, b in pairs_iter:
            da, db = houses.get(a, {}), houses.get(b, {})
            if not da.get('created') or not db.get('created'):
                continue
            n_pairs += 1
            same_author += da.get('author_id') is not None and da.get('author_id') == db.get('author_id')
            same_price += da.get('monthly_price') == db.get('monthly_price')
            same_region += (da.get('top_region'), da.get('sub_region')) == (db.get('top_region'), db.get('sub_region'))
    if n_pairs:
        lines.append('pairs with desc {} ({} groups sampled to {} pairs): same author {:.1f}% / same price {:.1f}% / same sub_region {:.1f}%'.format(
            n_pairs, n_capped, args.max_pairs, 100 * same_author / n_pairs, 100 * same_price / n_pairs, 100 * same_region / n_pairs))
    with open(os.path.join(args.out_dir, 'summary.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines), flush=True)
    log('summary.txt written')

    with open(os.path.join(args.out_dir, 'components.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['component_id', 'component_size', 'component_shared_photos', 'component_distinct_photos',
                    'vendor_house_id', 'n_photos', 'n_shared_with_group', 'sources'] + DESC)
        for ci, c in enumerate(comps):
            g = gstats[ci]
            for h in sorted(c):
                d = houses.get(h, {})
                w.writerow([ci, len(c), g['shared_photos'], g['distinct_photos'], h, len(photos[h]), house_shared[h],
                            '|'.join(sorted(sources[h]))] + [d.get(k) for k in DESC])
    log('components.csv written')

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
            shared_here = group_shared_photos(c, photos)
            parts.append('<div class="grp"><b>群 {} 戶</b>{}，共用照片 {} 張／群內相異 {} 張<table><tr><th>物件</th><th>首見</th><th>狀態</th><th>租金</th><th>坪</th><th>樓</th><th>區</th><th>地址</th><th>刊登者</th><th>仲介</th><th>era／來源</th><th>照片數</th></tr>'.format(len(hs), '（只列前 {} 戶）'.format(args.rows) if len(hs) > args.rows else '',
                          len(shared_here), len(set().union(*(photos[h] for h in hs)))))
            for h in hs[:args.rows]:
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
    log('review.html written')
    n_json = write_photos_json(os.path.join(args.out_dir, 'photos.json'), shared, houses, photos, sources, args.top,
                               comp_of, gstats, house_shared, args.json_houses)
    log('-> {}/review.html, components.csv, summary.txt, photos.json ({} photos; open tools/photo_viewer.html and load it)'.format(
        args.out_dir, n_json))
    if args.upload:
        import boto3
        bucket, _, prefix = args.upload[len('s3://'):].partition('/')
        s3 = boto3.client('s3')
        for name in ('summary.txt', 'components.csv', 'review.html', 'photos.json'):
            key = prefix.rstrip('/') + '/' + name
            s3.upload_file(os.path.join(args.out_dir, name), bucket, key)
            log('    uploaded s3://{}/{}'.format(bucket, key))


if __name__ == '__main__':
    main()
