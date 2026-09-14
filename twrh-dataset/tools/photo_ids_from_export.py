#!/usr/bin/env python3
'''photo_ids_from_export：從 RDS export 到 S3 的 Parquet（archive/rds/<export-id>/）抽每戶的 591 圖檔 id，
輸出與 `manage.py photoids` 同 schema 的 parquet（給 tools/photo_dup_review.py --etc）。無 DB。

    python tools/photo_ids_from_export.py --export s3://twrh-w2/archive/rds/<export-id> --out photo_ids/2026-09-13.parquet [--upload]
    python tools/photo_ids_from_export.py --export /path/to/export-dir --out …          # 已在本地的匯出

匯出目錄結構（2026-09-14 實測）：<export-id>/<db>/public.<table>/<n>/part-*.gz.parquet（＋ _SUCCESS 空檔）。
Spark 匯出的型別：timestamptz→字串 '2018-04-23 20:03:09.403624+00'、jsonb→字串（部分年代 detail_dict 是
JSON 再編碼一次的字串，regexp 直接對文字做、不解包）、PostGIS geometry→hex EWKB（POINT 自解，x=lat／y=lng
專案約定）。年代判定與 regexp 與 photoids.py 同一套。

記憶體：house 表只讀 photo_dup_review 會用到的描述欄，整表進 Arrow（850 萬列約 1 GB）；house_etc 逐 part
串流（S3 直接讀、不下載），每批用 pc.index_in 對 house.id 做位置查表再 take——不建 8.5M 筆的 Python dict。
'''
import argparse
import os
import re
import struct
import sys
from datetime import datetime

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyarrow import fs as pafs

PHOTO_ID_RE = re.compile(r'house/(?:active/)?\d{4}/\d{2}/\d{2}/(\d{15,20})')
SAMPLE_URL_RE = re.compile(r'(https?:[^"\\]*house/(?:active/)?\d{4}/\d{2}/\d{2}/\d{15,20}[^"\\]*)')

# 與 manage.py photoids 同 schema（photo_dup_review 的 DESC 欄都在）
FIELDS = [
    ('vendor_house_id', 'string'), ('created', 'ts'), ('crawled_at', 'ts'), ('detail_crawled_at', 'ts'),
    ('deal_status', 'int32'), ('deal_time', 'ts'), ('n_day_deal', 'int32'),
    ('top_region', 'int32'), ('sub_region', 'int32'), ('monthly_price', 'int64'), ('floor_ping', 'float64'),
    ('floor', 'int32'), ('total_floor', 'int32'), ('property_type', 'int32'), ('building_type', 'int32'),
    ('author_id', 'string'), ('agent_org', 'string'), ('contact', 'int32'), ('rough_address', 'string'),
    ('rough_lat', 'float64'), ('rough_lng', 'float64'), ('era', 'string'),
    ('photo_ids', 'list<string>'), ('n_photos', 'int32'), ('sample_url', 'string'),
]
KINDS = {'string': pa.string(), 'int32': pa.int32(), 'int64': pa.int64(), 'float64': pa.float64(),
         'ts': pa.timestamp('us', tz='UTC'), 'list<string>': pa.list_(pa.string())}
TS_COLS = [name for name, kind in FIELDS if kind == 'ts']
# 只讀 photo_dup_review 的 DESC 會用到的欄（crawled_at／detail_crawled_at／deal_time 等大字串欄不讀、
# 輸出留 NULL）：850 萬列 house 整表進 Arrow 約 1 GB，3 GB 的 task 才放得下
# rough_coordinate 不讀：hex EWKB 逐列解要把 850 萬個字串搬進 Python（9/14 首跑 3 GB task exit 137），
# 而 photo_dup_review 不用座標——輸出留 NULL（要座標時用 point_xy 對子集另算）
HOUSE_COLS = ['id', 'vendor_house_id', 'created', 'deal_status',
              'top_region', 'sub_region', 'monthly_price', 'floor_ping', 'floor', 'total_floor',
              'property_type', 'author_id', 'agent_org', 'contact', 'rough_address']
COMPUTED = ('era', 'photo_ids', 'n_photos', 'sample_url')


def arrow_schema():
    return pa.schema([pa.field(name, KINDS[kind], nullable=True) for name, kind in FIELDS])


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
        fmt = '<' if raw[0] == 1 else '>'
        gtype = struct.unpack(fmt + 'I', raw[1:5])[0]
        if gtype & 0xFF != 1:
            return None, None
        offset = 5 + (4 if gtype & 0x20000000 else 0)     # EWKB 帶 SRID 多 4 bytes
        return struct.unpack(fmt + 'dd', raw[offset:offset + 16])
    except Exception:  # noqa: BLE001
        return None, None


def cast_ts(column):
    ''''…+00' → '…+00:00' 再 cast；已是 timestamp 就原樣。'''
    if pa.types.is_timestamp(column.type):
        return column.cast(KINDS['ts'])
    fixed = pc.replace_substring_regex(column.cast(pa.string()), pattern=r'([+-]\d{2})$', replacement=r'\1:00')
    return pc.cast(fixed, KINDS['ts'], safe=False)


# --- 匯出目錄（本地或 S3）--------------------------------------------------------

class Export:
    def __init__(self, location):
        if location.startswith('s3://'):
            self.fs = pafs.S3FileSystem(region=os.environ.get('AWS_DEFAULT_REGION', 'us-west-2'))
            self.root = location[len('s3://'):].rstrip('/')
        else:
            self.fs = pafs.LocalFileSystem()
            self.root = os.path.abspath(location)

    def table_files(self, table):
        want = 'public.{}'.format(table)
        out = []
        for info in self.fs.get_file_info(pafs.FileSelector(self.root, recursive=True)):
            if not info.is_file or info.size == 0 or not info.path.endswith('.parquet'):
                continue
            parts = info.path.split('/')
            if any(p == want or p.endswith('.' + want) for p in parts):
                out.append(info.path)
        return sorted(out)

    def parquet(self, path):
        return pq.ParquetFile(path, filesystem=self.fs)


def load_houses(export, files):
    '''house 表 → 依 id 排好的 Arrow table（只留描述欄，型別轉成輸出契約）。'''
    chunks = []
    for path in files:
        pf = export.parquet(path)
        names = [c for c in HOUSE_COLS if c in pf.schema_arrow.names]
        t = pf.read(columns=names)
        cols = {}
        for name in names:
            col = t.column(name)
            if name in TS_COLS:
                cols[name] = cast_ts(col)
            elif name == 'rough_coordinate':
                xy = [point_xy(v) for v in col.to_pylist()]
                cols['rough_lat'] = pa.array([p[0] for p in xy], type=pa.float64())
                cols['rough_lng'] = pa.array([p[1] for p in xy], type=pa.float64())
            elif name == 'id':
                cols[name] = col.cast(pa.int64())
            elif name == 'author_id':
                cols[name] = col.cast(pa.string())
            else:
                cols[name] = col.cast(KINDS[dict(FIELDS)[name]])
        chunks.append(pa.table(cols))
    houses = pa.concat_tables(chunks, promote_options='default')
    return houses.sort_by('id')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--export', required=True, help='s3://bucket/archive/rds/<export-id> 或本地目錄')
    ap.add_argument('--out', required=True)
    ap.add_argument('--upload', action='store_true',
                    help='上 S3 <TWRH_RAW_BUCKET>/archive/analysis/photo_ids/<out 檔名>')
    ap.add_argument('--batch', type=int, default=100000)
    options = ap.parse_args()

    export = Export(options.export)
    etc_files = export.table_files('house_etc')
    house_files = export.table_files('house')
    if not etc_files or not house_files:
        sys.exit('export 目錄裡找不到 house_etc／house 的 parquet：{}'.format(options.export))
    print('house files {}, house_etc files {}'.format(len(house_files), len(etc_files)), flush=True)
    houses = load_houses(export, house_files)
    house_ids = houses.column('id')
    print('houses loaded: {} ({:.0f} MB in Arrow)'.format(houses.num_rows, houses.nbytes / 1e6), flush=True)

    schema = arrow_schema()
    os.makedirs(os.path.dirname(os.path.abspath(options.out)) or '.', exist_ok=True)
    tmp = options.out + '.tmp'
    writer = pq.ParquetWriter(tmp, schema, compression='zstd')
    n = n_photos_total = skipped = 0
    by_era = {}
    try:
        for path in etc_files:
            pf = export.parquet(path)
            for rb in pf.iter_batches(batch_size=options.batch, columns=['house_id', 'detail_dict']):
                texts = rb.column('detail_dict')
                keep = pc.is_valid(texts)
                rb = rb.filter(keep)
                if rb.num_rows == 0:
                    continue
                pos = pc.index_in(rb.column('house_id').cast(pa.int64()), value_set=house_ids)
                found = pc.is_valid(pos)
                skipped += rb.num_rows - pc.sum(found).as_py()
                rb = rb.filter(found)
                desc = houses.take(pos.filter(found))
                era, photos, n_photos, samples = [], [], [], []
                for text in rb.column('detail_dict').to_pylist():
                    ids = dedupe(PHOTO_ID_RE.findall(text))
                    m = SAMPLE_URL_RE.search(text)
                    era.append(era_of(text))
                    photos.append(ids)
                    n_photos.append(len(ids))
                    samples.append(m.group(1) if m else None)
                    n_photos_total += len(ids)
                    by_era[era[-1]] = by_era.get(era[-1], 0) + 1
                columns = []
                for name, kind in FIELDS:
                    if name == 'era':
                        columns.append(pa.array(era, type=pa.string()))
                    elif name == 'photo_ids':
                        columns.append(pa.array(photos, type=KINDS[kind]))
                    elif name == 'n_photos':
                        columns.append(pa.array(n_photos, type=pa.int32()))
                    elif name == 'sample_url':
                        columns.append(pa.array(samples, type=pa.string()))
                    elif name in desc.column_names:
                        columns.append(desc.column(name).cast(KINDS[kind]))
                    else:
                        columns.append(pa.nulls(rb.num_rows, type=KINDS[kind]))
                writer.write_table(pa.Table.from_arrays(columns, schema=schema))
                n += rb.num_rows
                if n // 500000 != (n - rb.num_rows) // 500000:
                    print('    {} rows, {} photo ids'.format(n, n_photos_total), flush=True)
    finally:
        writer.close()
    os.replace(tmp, options.out)
    print('=== photo_ids_from_export: {} houses ({} etc rows without house), {} photo ids, by era {} -> {} ({:.1f} MB)'
          .format(n, skipped, n_photos_total, by_era, options.out, os.path.getsize(options.out) / 1e6), flush=True)
    if options.upload:
        bucket = os.environ.get('TWRH_RAW_BUCKET')
        if not bucket:
            sys.exit('--upload 需要 TWRH_RAW_BUCKET')
        import boto3
        key = 'archive/analysis/photo_ids/{}'.format(os.path.basename(options.out))
        boto3.client('s3').upload_file(options.out, bucket, key)
        print('    uploaded s3://{}/{}'.format(bucket, key))


if __name__ == '__main__':
    main()
