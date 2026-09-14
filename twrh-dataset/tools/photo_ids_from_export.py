#!/usr/bin/env python3
'''photo_ids_from_export：從 RDS export 到 S3 的 Parquet（archive/rds/<export-id>/）抽每戶的 591 圖檔 id，
輸出與 `manage.py photoids` 同 schema 的 parquet（給 tools/photo_dup_review.py --etc）。無 DB。

    python tools/photo_ids_from_export.py --export s3://twrh-w2/archive/rds/<export-id> --out photo_ids/2026-09-13.parquet
    python tools/photo_ids_from_export.py --export /path/to/export-dir --out …      # 已 sync 到本地

export 目錄結構（AWS 固定）：<export-id>/<db>/<db>.<schema>.<table>/<n>/part-*.parquet；
detail_dict（jsonb）在 Parquet 裡是 string、rough_coordinate（PostGIS）是 WKB／EWKB 的 bytes 或 hex 字串
（本工具解 POINT；解不出留 NULL，不影響照片分析）。年代判定與 regexp 與 photoids.py 同一套。
'''
import argparse
import glob
import os
import re
import struct
import subprocess
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'django'))
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..'))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

PHOTO_ID_RE = re.compile(r'house/(?:active/)?\d{4}/\d{2}/\d{2}/(\d{15,20})')
SAMPLE_URL_RE = re.compile(r'(https?:[^"\\]*house/(?:active/)?\d{4}/\d{2}/\d{2}/\d{15,20}[^"\\]*)')

FIELDS = [
    ('vendor_house_id', 'string'), ('created', 'ts'), ('crawled_at', 'ts'), ('detail_crawled_at', 'ts'),
    ('deal_status', 'int32'), ('deal_time', 'ts'), ('n_day_deal', 'int32'),
    ('top_region', 'int32'), ('sub_region', 'int32'), ('monthly_price', 'int64'), ('floor_ping', 'float64'),
    ('floor', 'int32'), ('total_floor', 'int32'), ('property_type', 'int32'), ('building_type', 'int32'),
    ('author_id', 'string'), ('agent_org', 'string'), ('contact', 'int32'), ('rough_address', 'string'),
    ('rough_lat', 'float64'), ('rough_lng', 'float64'), ('era', 'string'),
    ('photo_ids', 'list<string>'), ('n_photos', 'int32'), ('sample_url', 'string'),
]
HOUSE_COLS = ['id', 'vendor_house_id', 'created', 'crawled_at', 'detail_crawled_at', 'deal_status', 'deal_time',
              'n_day_deal', 'top_region', 'sub_region', 'monthly_price', 'floor_ping', 'floor', 'total_floor',
              'property_type', 'building_type', 'author_id', 'agent_org', 'contact', 'rough_address',
              'rough_coordinate']


def arrow_schema():
    kinds = {'string': pa.string(), 'int32': pa.int32(), 'int64': pa.int64(), 'float64': pa.float64(),
             'ts': pa.timestamp('us', tz='UTC'), 'list<string>': pa.list_(pa.string())}
    return pa.schema([pa.field(name, kinds[kind], nullable=True) for name, kind in FIELDS])


def era_of(text):
    if 'images' in text:
        return 'v3'
    if 'favData' in text:
        return 'api'
    if 'imgs' in text:
        return 'v1'
    if 'misc' in text:
        return 'v2'
    return 'unknown'


def dedupe(ids):
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def point_xy(value):
    '''WKB／EWKB POINT（bytes 或 hex 字串）→ (x, y)；其他回 (None, None)。專案約定 x=lat、y=lng。'''
    if value is None:
        return None, None
    try:
        raw = bytes.fromhex(value) if isinstance(value, str) else bytes(value)
        little = raw[0] == 1
        fmt = '<' if little else '>'
        gtype = struct.unpack(fmt + 'I', raw[1:5])[0]
        offset = 5 + (4 if gtype & 0x20000000 else 0)     # EWKB 帶 SRID 多 4 bytes
        if gtype & 0xFF != 1:
            return None, None
        x, y = struct.unpack(fmt + 'dd', raw[offset:offset + 16])
        return x, y
    except Exception:  # noqa: BLE001
        return None, None


def table_files(export_dir, table):
    pattern = os.path.join(export_dir, '*', '*.public.{}'.format(table), '*', '*.parquet')
    files = sorted(glob.glob(pattern))
    if not files:
        files = sorted(glob.glob(os.path.join(export_dir, '**', '*.public.{}'.format(table), '**', '*.parquet'),
                              recursive=True))
    return files


def sync_from_s3(uri, dest):
    os.makedirs(dest, exist_ok=True)
    subprocess.run(['aws', 's3', 'sync', '--quiet', uri, dest], check=True)
    return dest


def load_houses(files):
    '''house 表 → {id: {desc 欄}}；只讀需要的欄（欄不存在就略過）。'''
    houses = {}
    for path in files:
        names = [c for c in HOUSE_COLS if c in pq.read_schema(path).names]
        table = pq.read_table(path, columns=names)
        cols = {c: table.column(c).to_pylist() for c in names}
        for i in range(table.num_rows):
            rec = {c: cols[c][i] for c in names}
            rec['rough_lat'], rec['rough_lng'] = point_xy(rec.pop('rough_coordinate', None))
            if rec.get('author_id') is not None:
                rec['author_id'] = str(rec['author_id'])
            houses[rec.pop('id')] = rec
    return houses


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--export', required=True, help='s3://bucket/archive/rds/<export-id> 或本地目錄')
    ap.add_argument('--out', required=True)
    ap.add_argument('--cache', default=os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'artifacts',
                                                    'analysis', 'rds-export'),
                    help='S3 匯出 sync 到本地的目錄')
    ap.add_argument('--batch', type=int, default=50000)
    options = ap.parse_args()

    export_dir = options.export
    if export_dir.startswith('s3://'):
        export_dir = sync_from_s3(export_dir, os.path.join(options.cache, export_dir.rstrip('/').rsplit('/', 1)[-1]))
    etc_files = table_files(export_dir, 'house_etc')
    house_files = table_files(export_dir, 'house')
    if not etc_files or not house_files:
        sys.exit('export 目錄裡找不到 house_etc／house 的 parquet：{}'.format(export_dir))
    print('house files {}, house_etc files {}'.format(len(house_files), len(etc_files)))
    houses = load_houses(house_files)
    print('houses loaded: {}'.format(len(houses)), flush=True)

    schema = arrow_schema()
    names = [name for name, _ in FIELDS]
    os.makedirs(os.path.dirname(os.path.abspath(options.out)), exist_ok=True)
    tmp = options.out + '.tmp'
    writer = pq.ParquetWriter(tmp, schema, compression='zstd')
    n = n_photos_total = skipped = 0
    by_era = {}
    batch = []
    try:
        for path in etc_files:
            pf = pq.ParquetFile(path)
            for rb in pf.iter_batches(batch_size=options.batch, columns=['house_id', 'detail_dict']):
                for house_id, text in zip(rb.column('house_id').to_pylist(), rb.column('detail_dict').to_pylist()):
                    if text is None:
                        continue
                    house = houses.get(house_id)
                    if house is None:
                        skipped += 1
                        continue
                    if not isinstance(text, str):
                        text = text.decode('utf-8', 'replace') if isinstance(text, (bytes, bytearray)) else str(text)
                    rec = {name: house.get(name) for name in names}
                    rec['era'] = era_of(text)
                    rec['photo_ids'] = dedupe(PHOTO_ID_RE.findall(text))
                    rec['n_photos'] = len(rec['photo_ids'])
                    m = SAMPLE_URL_RE.search(text)
                    rec['sample_url'] = m.group(1) if m else None
                    batch.append(rec)
                    n += 1
                    n_photos_total += rec['n_photos']
                    by_era[rec['era']] = by_era.get(rec['era'], 0) + 1
                    if len(batch) >= options.batch:
                        writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                        batch = []
                        if n % 500000 == 0:
                            print('    {} rows, {} photo ids'.format(n, n_photos_total), flush=True)
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
    finally:
        writer.close()
    os.replace(tmp, options.out)
    print('=== photo_ids_from_export: {} houses ({} etc rows without house), {} photo ids, by era {} -> {} ({:.1f} MB)'
          .format(n, skipped, n_photos_total, by_era, options.out, os.path.getsize(options.out) / 1e6))


if __name__ == '__main__':
    main()
