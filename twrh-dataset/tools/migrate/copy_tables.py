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
import time

from common import State, check_disk, load_django, log, source_cursor, \
    source_end_tx, target_conn

load_django()

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
    src.execute(f'select count(*), coalesce(min({pk}::text), \'\') from "{table}"')
    total = src.fetchone()[0]
    log(f'=== {table}: {total} rows ===')

    tcur = target.cursor()
    tcur.execute('drop table if exists staging')
    tcur.execute(f'create temp table staging (like "{table}" including defaults)')
    updates = ', '.join(f'{c} = excluded.{c}' for c in cols if c != pk)
    conflict = (f'do update set {updates} where excluded.updated > "{table}".updated'
                if guard else 'do nothing')

    offset, done = 0, 0
    limit = args.limit_rows if (args.limit_rows and table in LIMITABLE) else total
    while offset < limit:
        n = min(BATCH_ROWS, limit - offset)
        buf = io.StringIO()
        src.copy_expert(
            f'copy (select {col_list} from "{table}" order by {pk} '
            f'limit {n} offset {offset}) to stdout', buf)
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
        offset += n
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
