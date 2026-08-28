"""house / house_ts 與維度小表的分批搬運（COPY 進 staging → upsert 進正式表）。

COPY 文字序列化避開型別轉接（geometry/jsonb 原樣過境），staging 再 INSERT …
ON CONFLICT 拿到 upsert 語意；有 updated 欄位的表帶時間戳 guard。
依 FK 順序：vendor → sub_region → rental_author → crawlerrequest_stats →
region_ts → house → house_ts。

用法：
  poetry run python tools/migrate/copy_tables.py                 # 全部
  poetry run python tools/migrate/copy_tables.py --tables house_ts
  poetry run python tools/migrate/copy_tables.py --limit-rows 10000
"""
import argparse
import io
import os
import time

from common import State, check_disk, load_django, log, source_cursor, \
    source_end_tx, target_conn

load_django()

# 兩段 id 空間重疊（歷史段 1→~8M、本機段 3.5k→611k 各自從頭長）——歷史段原樣
# 過境、本機段整段平移，pk 才不互蓋。M3 設 100000000；house_ts 無 house FK，
# 只有 house_etc.house_id 要跟著平移（strip_house_etc 同值）。
# vendor / sub_region 是兩段共用的維度表（id 同值同義），不平移。
ID_OFFSET = int(os.environ.get('TWRH_MIGRATE_ID_OFFSET', '0'))
OFFSET_TABLES = {'house', 'house_ts', 'crawlerrequest_stats', 'region_ts'}

# (table, pk, has_updated_guard)
TABLES = [
    ('vendor', 'id', False),
    ('sub_region', 'id', False),
    ('rental_author', 'uuid', True),
    ('crawlerrequest_stats', 'id', False),
    ('region_ts', 'id', True),
    ('house', 'id', True),
    ('house_ts', 'id', True),
]
BATCH_ROWS = 50000
# --limit-rows 只作用在無人依賴的大表；維度表與 house 被 FK 指著，砍了會連鎖爆
LIMITABLE = {'house_ts'}


def columns_of(cur, table):
    cur.execute(
        'select column_name from information_schema.columns '
        'where table_schema = %s and table_name = %s order by ordinal_position',
        ['public', table])
    return [r[0] for r in cur.fetchall()]


def copy_table(table, pk, guard, target, args, state):
    t0 = time.time()
    src = source_cursor()
    cols = columns_of(src, table)
    col_list = ', '.join(cols)
    # 來源側套 offset（僅整數序號 pk；uuid pk 與維度表不平移）
    shift = ID_OFFSET if (ID_OFFSET and table in OFFSET_TABLES) else 0
    sel_list = ', '.join(
        f'{c} + {shift} as {c}' if (shift and c == pk == 'id') else c
        for c in cols)
    src.execute(f'select count(*), coalesce(min({pk}::text), \'\') from "{table}"')
    total = src.fetchone()[0]
    log(f'=== {table}: {total} rows ===')

    tcur = target.cursor()
    tcur.execute('drop table if exists staging')
    tcur.execute(f'create temp table staging (like "{table}" including defaults)')
    updates = ', '.join(f'{c} = excluded.{c}' for c in cols if c != pk)
    conflict = (f'do update set {updates} where excluded.updated > "{table}".updated'
                if guard else 'do nothing')

    # keyset 分頁（where pk > last）——offset 分頁在百萬列級是 O(n²)，
    # M2 歷史段（7.9M 列、t4g.micro）實測速率隨 offset 直線下滑
    from psycopg2.extensions import adapt
    pk_idx = cols.index(pk)
    done = 0
    last = None  # 來源側邊界（offset 平移前的值）
    limit = args.limit_rows if (args.limit_rows and table in LIMITABLE) else total
    while done < limit:
        n = min(BATCH_ROWS, limit - done)
        cond = f'where {pk} > {adapt(last).getquoted().decode()}' if last is not None else ''
        buf = io.StringIO()
        src.copy_expert(
            f'copy (select {sel_list} from "{table}" {cond} '
            f'order by {pk} limit {n}) to stdout', buf)
        raw = buf.getvalue()
        if not raw:
            break
        buf.seek(0)
        tcur.execute('truncate staging')
        tcur.copy_expert(f'copy staging ({col_list}) from stdin', buf)
        staged = tcur.rowcount
        if staged == 0:
            break
        tcur.execute(f'insert into "{table}" ({col_list}) '
                     f'select {col_list} from staging '
                     f'on conflict ({pk}) {conflict}')
        target.commit()
        done += staged
        # 下一批邊界＝這批最後一列的 pk（COPY 文字格式取尾行；整數 pk 扣回平移）
        last = raw.rsplit('\n', 2)[-2].split('\t')[pk_idx]
        if shift:
            last = int(last) - shift
        elif pk == 'id':
            last = int(last)
        if total > BATCH_ROWS:
            rate = done / (time.time() - t0)
            log(f'  {table}: {done}/{limit} rows, {rate:.0f} rows/s')
        check_disk()

    # sequence 對齊，讓新 DB 後續寫入不撞既有 id
    if pk == 'id':
        tcur.execute(
            "select setval(pg_get_serial_sequence(%s, 'id'), "
            f'coalesce((select max(id) from "{table}"), 1))', [table])
    tcur.execute('drop table staging')
    target.commit()
    source_end_tx()
    state.mark(table, rows=done, secs=round(time.time() - t0))
    log(f'  {table}: OK — {done} rows, {time.time() - t0:.0f}s')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', nargs='*')
    ap.add_argument('--limit-rows', type=int, help='每表只搬前 N 列（演練）')
    ap.add_argument('--redo', action='store_true')
    args = ap.parse_args()

    state = State('copy_tables' + ('.rehearsal' if args.limit_rows else ''))
    target = target_conn()
    for table, pk, guard in TABLES:
        if args.tables and table not in args.tables:
            continue
        if state.done(table) and not args.redo:
            log(f'=== {table}: marker 已存在，跳過 ===')
            continue
        copy_table(table, pk, guard, target, args, state)
    target.close()
    log('all done. state: ' + state.path)


if __name__ == '__main__':
    main()
