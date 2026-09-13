'''photoids：從 house_etc.detail_dict 抽每戶的 591 圖檔 id（分析用，不進 pipeline）。

    manage.py photoids [--out PATH] [--limit N] [--upload] [--vendor NAME]

用途：重複／重刊研究（schema 1.0 草案 §2.7）的歷年照片資料。591 圖檔 URL 各年代長相不同，
但路徑裡的 18 位數字 id 從 2015 年沿用至今：
    2018–2021  imgs[]         https://hp1.591.com.tw/house/active/2016/03/16/145810200168235401_765x517.water3.jpg
    2022–2023  favData.thumb  https://img1.591.com.tw/house/2023/07/17/168960204377945404.jpg!190x150.water2.jpg（只有一張縮圖）
    2024–2026/08 misc/tags 版 dict 沒有照片（要從 raw HTML 月包另抽，tools/photo_ids_from_raws.py）
    2026/09–   images[]       https://img2.591.com.tw/house/2021/07/16/162642443703678974.jpg!1000x.water2.jpg
部分年代 detail_dict 存成 JSON 字串（jsonb string），regexp 直接對 ::text 做、不解包。
`user/…` 的頭像路徑不含 `house/`，自然排除。

輸出 parquet 一戶一列：House 現值的描述欄（人眼審核用）＋era＋photo_ids（list<string>）＋一個
可點的 sample_url。8.3M 列用 server-side cursor 分批寫（ParquetWriter），記憶體固定。
--upload 上 S3 `archive/analysis/photo_ids/<date>.parquet`（task role 只開 archive/*）。
'''
import os
import re
from datetime import date as date_cls

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from rental import artifacts
from rental.models import Vendor

PHOTO_ID_RE = r'house/(?:active/)?\d{4}/\d{2}/\d{2}/(\d{15,20})'
SAMPLE_URL_RE = r'(https?:[^"\\]*house/(?:active/)?\d{4}/\d{2}/\d{2}/\d{15,20}[^"\\]*)'

SQL = '''
SELECT h.vendor_house_id, h.created, h.crawled_at, h.detail_crawled_at, h.deal_status, h.deal_time,
       h.n_day_deal, h.top_region, h.sub_region, h.monthly_price, h.floor_ping, h.floor, h.total_floor,
       h.property_type, h.building_type, h.author_id::text AS author_id, h.agent_org, h.contact, h.rough_address,
       ST_X(h.rough_coordinate) AS rough_lat, ST_Y(h.rough_coordinate) AS rough_lng,
       CASE WHEN t LIKE '%%images%%' THEN 'v3'
            WHEN t LIKE '%%favData%%' THEN 'api'
            WHEN t LIKE '%%imgs%%' THEN 'v1'
            WHEN t LIKE '%%misc%%' THEN 'v2'
            ELSE 'unknown' END AS era,   -- 不比引號：部分年代 dict 是 JSON 字串、引號帶跳脫
       ARRAY(SELECT m[1] FROM regexp_matches(t, %(pid)s, 'g') m) AS photo_ids,
       (SELECT m[1] FROM regexp_matches(t, %(url)s) m LIMIT 1) AS sample_url
FROM house h
JOIN house_etc e ON e.house_id = h.id
CROSS JOIN LATERAL (SELECT e.detail_dict::text AS t) x
WHERE h.vendor_id = %(vendor)s AND e.detail_dict IS NOT NULL
'''

FIELDS = [
    ('vendor_house_id', 'string'), ('created', 'ts'), ('crawled_at', 'ts'), ('detail_crawled_at', 'ts'),
    ('deal_status', 'int32'), ('deal_time', 'ts'), ('n_day_deal', 'int32'),
    ('top_region', 'int32'), ('sub_region', 'int32'), ('monthly_price', 'int64'), ('floor_ping', 'float64'),
    ('floor', 'int32'), ('total_floor', 'int32'), ('property_type', 'int32'), ('building_type', 'int32'),
    ('author_id', 'string'), ('agent_org', 'string'), ('contact', 'int32'), ('rough_address', 'string'),
    ('rough_lat', 'float64'), ('rough_lng', 'float64'), ('era', 'string'),
    ('photo_ids', 'list<string>'), ('n_photos', 'int32'), ('sample_url', 'string'),
]


def arrow_schema():
    import pyarrow as pa
    kinds = {'string': pa.string(), 'int32': pa.int32(), 'int64': pa.int64(), 'float64': pa.float64(),
             'ts': pa.timestamp('us', tz='UTC'), 'list<string>': pa.list_(pa.string())}
    return pa.schema([pa.field(name, kinds[kind], nullable=True) for name, kind in FIELDS])


def dedupe(ids):
    seen, out = set(), []
    for i in ids or ():
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


class Command(BaseCommand):
    help = 'Extract 591 photo ids per house from house_etc.detail_dict into parquet (analysis)'

    def add_arguments(self, parser):
        parser.add_argument('--vendor', default='591 租屋網')
        parser.add_argument('--out')
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--batch', type=int, default=20000)
        parser.add_argument('--upload', action='store_true')

    def handle(self, *_args, **options):
        import pyarrow as pa
        import pyarrow.parquet as pq
        vendor = Vendor.objects.get(name=options['vendor'])
        today = date_cls.today().isoformat()
        out = options['out'] or os.path.join(artifacts.artifact_dir(), 'analysis', 'photo_ids', today + '.parquet')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        sql = SQL + (' LIMIT %(limit)s' if options['limit'] else '')
        params = {'pid': PHOTO_ID_RE, 'url': SAMPLE_URL_RE, 'vendor': vendor.id, 'limit': options['limit']}
        schema = arrow_schema()
        names = [name for name, _ in FIELDS]
        n = n_photos_total = 0
        by_era = {}
        tmp = out + '.tmp'
        writer = pq.ParquetWriter(tmp, schema, compression='zstd')
        try:
            # psycopg2 named cursor＝server-side：8.3M 列不會整批進記憶體（要在交易內）
            with transaction.atomic(), connection.connection.cursor(name='photoids') as cur:
                cur.itersize = options['batch']
                cur.execute(sql, params)
                batch = []
                for row in cur:
                    rec = dict(zip(names[:-3], row[:-2]))
                    rec['photo_ids'] = dedupe(row[-2])
                    rec['n_photos'] = len(rec['photo_ids'])
                    rec['sample_url'] = row[-1]
                    batch.append(rec)
                    n += 1
                    n_photos_total += rec['n_photos']
                    by_era[rec['era']] = by_era.get(rec['era'], 0) + 1
                    if len(batch) >= options['batch']:
                        writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                        batch = []
                        if n % 200000 == 0:
                            print('    {} rows, {} photo ids'.format(n, n_photos_total), flush=True)
                if batch:
                    writer.write_table(pa.Table.from_pylist(batch, schema=schema))
        finally:
            writer.close()
        os.replace(tmp, out)
        print('=== photoids {}: {} houses, {} photo ids, by era {} -> {} ({:.1f} MB)'.format(
            vendor.name, n, n_photos_total, by_era, out, os.path.getsize(out) / 1e6))
        if options['upload']:
            bucket = os.environ.get('TWRH_RAW_BUCKET')
            if not bucket:
                print('!!! TWRH_RAW_BUCKET unset, skip upload')
                return
            import boto3
            key = 'archive/analysis/photo_ids/{}.parquet'.format(today)
            boto3.client('s3').upload_file(out, bucket, key)
            print('    uploaded s3://{}/{}'.format(bucket, key))
