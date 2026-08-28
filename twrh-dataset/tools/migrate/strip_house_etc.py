"""house_etc 剝離式搬運：raw 打包（本機目錄扮演 S3）、其餘欄位 upsert 進目標 DB。

以 updated 月份為原子單位（中斷重跑整月，upsert 冪等）：
  讀一個月 → detail_raw/list_raw 進 <YYYY-MM>.tar.zst（member: <house_id>.detail.html
  / .list.html）＋ index json → 其餘欄位 upsert → 抽樣驗包 → 記 marker →
  刪包（--keep-packs 保留；index 永遠保留，正式版 index 也是要跟包一起上 S3 的）。

用法：
  poetry run python tools/migrate/strip_house_etc.py                # 全部月份
  poetry run python tools/migrate/strip_house_etc.py --months 2025-10
  poetry run python tools/migrate/strip_house_etc.py --limit-rows 10000   # 小 range 演練
"""
import argparse
import io
import json
import os
import random
import subprocess
import sys
import tarfile
import time

from common import (State, check_disk, load_django, log, s3_prefix, s3_upload,
                    source_cursor, source_end_tx, target_conn, work_dir)

load_django()

from psycopg2.extras import Json, execute_values  # noqa: E402  (psycopg2 由 django backend 保證存在)

# 本機段 id 平移（與 copy_tables 的 house 同值）；包的 member 名與 index key
# 也用平移後 id——之後 rerun 工具照新 DB 的 house_id 找包才對得上
ID_OFFSET = int(os.environ.get('TWRH_MIGRATE_ID_OFFSET', '0'))

COLS = ['created', 'updated', 'house_id', 'vendor_house_id',
        'detail_dict', 'could_be_rooftop', 'vendor_id']
UPSERT_SQL = f"""
    INSERT INTO house_etc ({', '.join(COLS)}, list_raw, detail_raw)
    VALUES %s
    ON CONFLICT (house_id) DO UPDATE SET
        {', '.join(f'{c} = excluded.{c}' for c in COLS if c != 'house_id')}
    WHERE excluded.updated > house_etc.updated
"""
TEMPLATE = '(' + ', '.join(['%s'] * len(COLS)) + ', NULL, NULL)'
FETCH_SIZE = 500
UPSERT_BATCH = 1000
SAMPLE_SIZE = 20


def list_months():
    cur = source_cursor()
    cur.execute("select to_char(updated,'YYYY-MM'), count(*) from house_etc "
                "group by 1 order by 1")
    return cur.fetchall()


def open_pack(path):
    """tarfile 串流餵給 zstd stdin——不落未壓縮中間檔。"""
    proc = subprocess.Popen(['zstd', '-q', '-3', '-f', '-o', path],
                            stdin=subprocess.PIPE)
    tar = tarfile.open(mode='w|', fileobj=proc.stdin)
    return tar, proc


def add_member(tar, name, text, mtime):
    data = text.encode('utf-8')
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = mtime
    tar.addfile(info, io.BytesIO(data))
    return len(data)


def verify_pack(pack_path, index, src_ids):
    """tar 總 member 數對 index，抽樣解出來 bit 比對 DB 原文。"""
    listed = subprocess.run(['tar', '-I', 'zstd', '-tf', pack_path],
                            capture_output=True, text=True, check=True)
    n_members = len(listed.stdout.splitlines())
    n_expected = sum(len(v) for v in index.values())
    assert n_members == n_expected, f'member count {n_members} != index {n_expected}'

    cur = source_cursor()
    for house_id in random.sample(list(index), min(SAMPLE_SIZE, len(index))):
        cur.execute('select detail_raw, list_raw from house_etc where house_id = %s',
                    [src_ids[house_id]])
        detail_raw, list_raw = cur.fetchone()
        for kind, original in (('detail', detail_raw), ('list', list_raw)):
            member = f'{house_id}.{kind}.html'
            if member not in index[house_id]:
                continue
            out = subprocess.run(['tar', '-I', 'zstd', '-xOf', pack_path, member],
                                 capture_output=True, check=True)
            assert out.stdout == original.encode('utf-8'), f'{member} content mismatch'
    return n_members


def load_house_map(target):
    """跨段撞鍵的 house id remap（copy_tables 產出）；無表或空＝無撞鍵。"""
    cur = target.cursor()
    cur.execute("select to_regclass('migrate_house_map')")
    if cur.fetchone()[0] is None:
        return {}
    cur.execute('select src_id, dst_id from migrate_house_map')
    return dict(cur.fetchall())


def run_month(month, n_rows, target, house_map, args, state):
    free = check_disk()
    log(f'=== {month}: {n_rows} rows (free disk {free:.1f} GB) ===')
    t0 = time.time()
    pack_path = os.path.join(work_dir(), f'{month}.tar.zst')
    index_path = os.path.join(work_dir(), f'{month}.index.json')

    src = source_cursor(name=f'strip_{month.replace("-", "")}')
    src.itersize = FETCH_SIZE
    src.execute(
        "select created, updated, house_id, vendor_house_id, detail_dict, "
        "could_be_rooftop, vendor_id, detail_raw, list_raw "
        "from house_etc where updated >= %s::date "
        "and updated < %s::date + interval '1 month' "
        + ('' if not args.limit_rows else f'order by house_id limit {args.limit_rows}'),
        [month + '-01', month + '-01'])

    tar, proc = open_pack(pack_path)
    index, src_ids, batch, done, packed = {}, {}, [], 0, 0
    tcur = target.cursor()
    for row in src:
        created, updated, house_id, vhid, ddict, rooftop, vendor_id, draw, lraw = row
        src_id = house_id
        house_id += ID_OFFSET
        house_id = house_map.get(house_id, house_id)
        mtime = int(updated.timestamp())
        entry = {}
        if draw:
            entry[f'{house_id}.detail.html'] = add_member(
                tar, f'{house_id}.detail.html', draw, mtime)
        if lraw:
            entry[f'{house_id}.list.html'] = add_member(
                tar, f'{house_id}.list.html', lraw, mtime)
        packed += sum(entry.values())
        if entry:
            index[str(house_id)] = entry
            src_ids[str(house_id)] = src_id
        batch.append((created, updated, house_id, vhid,
                      Json(ddict) if ddict is not None else None, rooftop, vendor_id))
        if len(batch) >= UPSERT_BATCH:
            execute_values(tcur, UPSERT_SQL, batch, template=TEMPLATE)
            target.commit()
            batch.clear()
        done += 1
        if done % 20000 == 0:
            rate = done / (time.time() - t0)
            log(f'  {month}: {done}/{n_rows} rows, {packed/2**30:.1f} GB packed, '
                f'{rate:.0f} rows/s')
            check_disk()
    if batch:
        execute_values(tcur, UPSERT_SQL, batch, template=TEMPLATE)
        target.commit()
    src.close()
    source_end_tx()
    tar.close()
    proc.stdin.close()
    assert proc.wait() == 0, 'zstd failed'

    with open(index_path, 'w') as f:
        json.dump(index, f)
    n_members = verify_pack(pack_path, index, src_ids)
    pack_size = os.path.getsize(pack_path)
    secs = time.time() - t0
    log(f'  {month}: OK — {done} rows, {n_members} members, '
        f'raw {packed/2**30:.2f} GB → pack {pack_size/2**30:.2f} GB, {secs:.0f}s')

    # 驗完先上 S3 再刪本機包（M2/M3 正式路徑）；未設 S3 prefix 即 M0 彩排語意
    s3_uri = None
    if n_members and s3_prefix():
        s3_uri = s3_upload(pack_path, f'{month}.tar.zst')
        s3_upload(index_path, f'{month}.index.json', storage_class=None)
        log(f'  {month}: uploaded {s3_uri}')
    elif n_members and not args.keep_packs:
        log(f'  {month}: !! no TWRH_MIGRATE_S3_PREFIX — pack will be deleted '
            '(source DB still holds raw)')
    if not args.keep_packs:
        os.remove(pack_path)
    state.mark(month, rows=done, members=n_members, raw_bytes=packed,
               pack_bytes=pack_size, secs=round(secs), kept=bool(args.keep_packs),
               s3=s3_uri)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--months', nargs='*', help='只跑這些月份（YYYY-MM）')
    ap.add_argument('--limit-rows', type=int, help='每月只取前 N 列（小 range 演練）')
    ap.add_argument('--keep-packs', action='store_true', help='驗完不刪包')
    ap.add_argument('--redo', action='store_true', help='忽略 marker 重跑')
    args = ap.parse_args()

    state = State('strip_house_etc' + ('.rehearsal' if args.limit_rows else ''))
    target = target_conn()
    house_map = load_house_map(target)
    if house_map:
        log(f'house id remap: {len(house_map)} 筆（跨段撞鍵）')
    months = list_months()
    for month, n_rows in months:
        if args.months and month not in args.months:
            continue
        if state.done(month) and not args.redo:
            log(f'=== {month}: marker 已存在，跳過（--redo 重跑）===')
            continue
        run_month(month, n_rows, target, house_map, args, state)
    target.close()
    log('all done. state: ' + state.path)


if __name__ == '__main__':
    main()
