#!/usr/bin/env python3
'''photo_ids_from_raws：從 raw HTML 日包／月包抽每戶的 591 圖檔 id（分析用，無 DB）。

    python tools/photo_ids_from_raws.py --out photo_ids_raws.parquet raws/591/2024-01.tar.zst raws/591/2026-08.tar.zst

補 `manage.py photoids` 抓不到的年代：2024–2026/08 的 detail_dict（misc/tags 版）不存照片，
但 raw HTML 月包（S3 raw/591/<YYYY-MM>.tar.zst；2024-01～05、09、10、2025-10～12、2026-03～05、08）
與 9/4 起的日包有整頁，圖檔 URL 在 nuxt payload 裡。同一條 regexp：路徑裡的 18 位數字 id
（見 photoids.py 的年代對照）。一戶在多個包出現就多列，帶 pack 欄，合併時自行取聯集。
'''
import argparse
import os
import re
import subprocess
import sys
import tarfile

PHOTO_ID_RE = re.compile(rb'house/(?:active/)?\d{4}/\d{2}/\d{2}/(\d{15,20})')
SAMPLE_URL_RE = re.compile(rb'(https?:[^"\'\\\s<>]*house/(?:active/)?\d{4}/\d{2}/\d{2}/\d{15,20}[^"\'\\\s<>]*)')


def iter_pack(pack_path):
    proc = subprocess.Popen(['zstd', '-dc', pack_path], stdout=subprocess.PIPE)
    with tarfile.open(mode='r|', fileobj=proc.stdout) as tar:
        for info in tar:
            if not info.isfile():
                continue
            yield info.name, tar.extractfile(info).read()
    proc.stdout.close()
    proc.wait()


def extract(body):
    seen, ids = set(), []
    for m in PHOTO_ID_RE.finditer(body):
        pid = m.group(1).decode()
        if pid not in seen:
            seen.add(pid)
            ids.append(pid)
    m = SAMPLE_URL_RE.search(body)
    return ids, (m.group(1).decode(errors='replace') if m else None)


def main():
    import pyarrow as pa
    import pyarrow.parquet as pq
    ap = argparse.ArgumentParser()
    ap.add_argument('packs', nargs='+')
    ap.add_argument('--out', required=True)
    ap.add_argument('--batch', type=int, default=20000)
    args = ap.parse_args()
    schema = pa.schema([('vendor_house_id', pa.string()), ('pack', pa.string()), ('member', pa.string()),
                        ('photo_ids', pa.list_(pa.string())), ('n_photos', pa.int32()), ('sample_url', pa.string())])
    writer = pq.ParquetWriter(args.out + '.tmp', schema, compression='zstd')
    total = with_photos = 0
    try:
        for pack in args.packs:
            tag = os.path.basename(pack).split('.tar')[0]
            n = n_with = 0
            batch = []
            for member, body in iter_pack(pack):
                base = os.path.basename(member)
                if not base.endswith('.detail.html'):
                    continue
                house_id = base.rsplit('.', 2)[0]
                ids, url = extract(body)
                batch.append({'vendor_house_id': house_id, 'pack': tag, 'member': member,
                              'photo_ids': ids, 'n_photos': len(ids), 'sample_url': url})
                n += 1
                n_with += bool(ids)
                if len(batch) >= args.batch:
                    writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                    batch = []
            if batch:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
            print('=== {}: {} detail pages, {} with photos'.format(tag, n, n_with), flush=True)
            total += n
            with_photos += n_with
    finally:
        writer.close()
    os.replace(args.out + '.tmp', args.out)
    print('=== total {} pages, {} with photos -> {}'.format(total, with_photos, args.out))


if __name__ == '__main__':
    sys.exit(main())
