"""annual-dump（s3://twrh/misc/annual-dump/）→ 目標 house_etc。

舊 RDS t4g.micro credits 燒乾時的第二來源（aws-deployment-plan 既定預案，
2026-08-29 M2 實際啟用）：pre-2024 的 house_etc 本就沒有 raw，detail_dict
從 dump 直載，完全不碰舊 RDS；2024 帶 raw 的月份仍走 strip_house_etc——
兩者對同列的 upsert 帶相同 updated，互為 no-op，冪等互補。
跨段撞鍵的 house id（migrate_house_map）照 map remap，remapped 列逐筆 upsert
（同批同 pk 兩次會炸 ON CONFLICT）。

用法（本機，twrh profile 有 AnnualDumpRead；不讀來源 DB）：
  poetry run python tools/migrate/load_annual_dump.py                # 全部
  poetry run python tools/migrate/load_annual_dump.py --keys house_etc_2018_001.jsonl.gz
"""
import argparse
import gzip
import json
import time

import boto3
from psycopg2.extras import Json, execute_values

from common import State, log, target_conn

BUCKET, PREFIX = 'twrh', 'misc/annual-dump/'
UPSERT = """
    INSERT INTO house_etc (created, updated, house_id, vendor_house_id,
                           detail_dict, vendor_id, list_raw, detail_raw)
    VALUES %s
    ON CONFLICT (house_id) DO UPDATE SET
        created = excluded.created, updated = excluded.updated,
        vendor_house_id = excluded.vendor_house_id,
        detail_dict = excluded.detail_dict, vendor_id = excluded.vendor_id
    WHERE excluded.updated > house_etc.updated
"""
TEMPLATE = '(%s, %s, %s, %s, %s, %s, NULL, NULL)'
BATCH = 1000


def load_house_map(target):
    cur = target.cursor()
    cur.execute("select to_regclass('migrate_house_map')")
    if cur.fetchone()[0] is None:
        return {}
    cur.execute('select src_id, dst_id from migrate_house_map')
    return dict(cur.fetchall())


def as_row(d, hmap):
    hid = int(d['house_id'])
    hid = hmap.get(hid, hid)
    ddict = d.get('detail_dict')
    return (d['created'], d['updated'], hid, d['vendor_house_id'],
            Json(ddict) if ddict is not None else None, int(d['vendor_id'])), \
        int(d['house_id']) in hmap


def run_key(s3, key, target, hmap, state):
    t0 = time.time()
    body = s3.get_object(Bucket=BUCKET, Key=key)['Body']
    tcur = target.cursor()
    batch, done = [], 0
    for line in gzip.GzipFile(fileobj=body):
        row, remapped = as_row(json.loads(line), hmap)
        if remapped:
            # remap 後與既有列同 pk——逐筆 upsert，避免同批同 pk 兩次
            execute_values(tcur, UPSERT, [row], template=TEMPLATE)
        else:
            batch.append(row)
        if len(batch) >= BATCH:
            execute_values(tcur, UPSERT, batch, template=TEMPLATE)
            target.commit()
            batch.clear()
        done += 1
        if done % 100000 == 0:
            log(f'  {key}: {done} rows, {done/(time.time()-t0):.0f} rows/s')
    if batch:
        execute_values(tcur, UPSERT, batch, template=TEMPLATE)
    target.commit()
    secs = time.time() - t0
    state.mark(key, rows=done, secs=round(secs))
    log(f'  {key}: OK — {done} rows, {secs:.0f}s')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keys', nargs='*', help='只跑這些檔名（basename）')
    ap.add_argument('--redo', action='store_true')
    args = ap.parse_args()

    s3 = boto3.client('s3')
    keys = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        keys += [o['Key'] for o in page.get('Contents', []) if o['Key'].endswith('.jsonl.gz')]
    keys.sort()

    target = target_conn()
    hmap = load_house_map(target)
    log(f'{len(keys)} dump files; house id remap: {len(hmap)} 筆')
    state = State('load_annual_dump')
    for key in keys:
        base = key.rsplit('/', 1)[-1]
        if args.keys and base not in args.keys:
            continue
        if state.done(base) and not args.redo:
            log(f'=== {base}: marker 已存在，跳過 ===')
            continue
        log(f'=== {base} ===')
        run_key(s3, key, target, hmap, state)
    target.close()
    log('all done. state: ' + state.path)


if __name__ == '__main__':
    main()
