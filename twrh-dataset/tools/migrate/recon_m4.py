"""M4 遷移對帳：跨段 count 核算＋本機段抽樣比對＋raw 全 NULL 檢查。

verify_counts.py 是 M0 彩排的「來源＝目標」直比版；正式遷移後目標是
歷史段（舊 RDS，已不連線）＋本機段（twrh2025）合併的結果，改用本檔。

核算式（歷史段基準取 M2 copy 當下 count，寫死在 OLD_*）：
- house      = OLD_HOUSE − map(src<1e8) + local_house − map(src≥1e8)
               （map = migrate_house_map，自然鍵 (vendor, vendor_house_id) 合併：
                 src<1e8 是舊段內部重複、src≥1e8 是跨段長壽刊登）
- author     = OLD_AUTHOR + local_author − migrate_author_map（truth 合併，不分段）
- house_ts   = local house_ts（歷史段 2024 TS 已拍板 trim 光）
- house_etc  = 無獨立基準（dump loader marker 隨 task 遺失）：
               本機段以「local etc = 目標 etc(≥1e8) + 被 remap 進歷史 id 的 etc」
               精確對帳；歷史段報 houses_without_etc 分布供檢視。

用法（連線同 copy_tables：Django default=twrh2025、TWRH_MIGRATE_TARGET_DSN=新 RDS）：
  poetry run python tools/migrate/recon_m4.py
"""
import random
import sys

from common import load_django, log, source_cursor, target_conn

load_django()

OFFSET = 100_000_000
OLD_HOUSE = 7_859_602
OLD_AUTHOR = 1_013_617
SAMPLE = 50

HOUSE_COLS = ('vendor_house_id', 'vendor_id', 'monthly_price', 'deal_status',
              'created', 'updated')
TS_COLS = ('vendor_house_id', 'vendor_id', 'year', 'month', 'day',
           'monthly_price', 'updated')
ETC_COLS = ('vendor_house_id', 'vendor_id', 'created', 'updated', 'detail_dict',
            'could_be_rooftop')

failed = False


def check(name, actual, expected):
    global failed
    ok = actual == expected
    if not ok:
        failed = True
    log(f'  {name:44s} {actual:>9} vs expected {expected:>9}  '
        + ('OK' if ok else '!! MISMATCH'))


def one(cur, sql, args=None):
    cur.execute(sql, args or [])
    return cur.fetchone()[0]


def main():
    global failed
    random.seed(4)  # 抽樣可重現，重跑同一批
    src = source_cursor()
    tcur = target_conn().cursor()

    log('--- 本機段基準（twrh2025）---')
    local = {t: one(src, f'select count(*) from "{t}"')
             for t in ('house', 'rental_author', 'house_ts', 'house_etc')}
    for t, n in local.items():
        log(f'  local {t:24s} {n:>9}')

    log('--- migrate_*_map ---')
    map_lo = one(tcur, 'select count(*) from migrate_house_map where src_id < %s', [OFFSET])
    map_hi = one(tcur, 'select count(*) from migrate_house_map where src_id >= %s', [OFFSET])
    author_map = one(tcur, 'select count(*) from migrate_author_map')
    log(f'  house_map src<1e8(舊段內部重複)={map_lo}  src>=1e8(跨段合併)={map_hi}  '
        f'author_map={author_map}')

    log('--- count 核算 ---')
    check('house', one(tcur, 'select count(*) from house'),
          OLD_HOUSE - map_lo + local['house'] - map_hi)
    check('rental_author', one(tcur, 'select count(*) from rental_author'),
          OLD_AUTHOR + local['rental_author'] - author_map)
    check('house_ts', one(tcur, 'select count(*) from house_ts'), local['house_ts'])
    check('house_ts id<1e8 (歷史段應已 trim 光)',
          one(tcur, 'select count(*) from house_ts where id < %s', [OFFSET]), 0)

    # 本機段 etc：remap 進歷史 id 的列要扣回來才對得上
    tcur.execute('select src_id from migrate_house_map where src_id >= %s', [OFFSET])
    remapped_local_ids = [r[0] - OFFSET for r in tcur.fetchall()]
    remapped_with_etc = one(
        src, 'select count(*) from house_etc where house_id = any(%s)',
        [remapped_local_ids])
    check('house_etc house_id>=1e8 (本機段)',
          one(tcur, 'select count(*) from house_etc where house_id >= %s', [OFFSET]),
          local['house_etc'] - remapped_with_etc)

    log('--- raw 全 NULL ---')
    check('house_etc raw not null',
          one(tcur, 'select count(*) from house_etc '
                    'where detail_raw is not null or list_raw is not null'), 0)

    log('--- houses_without_etc 檢視（歷史段無硬基準，供人工判讀）---')
    etc_lo = one(tcur, 'select count(*) from house_etc where house_id < %s', [OFFSET])
    log(f'  house_etc house_id<1e8 (dump+2024 strip)   {etc_lo:>9}')
    tcur.execute(
        'select extract(year from h.created)::int, count(*) from house h '
        'left join house_etc e on e.house_id = h.id '
        'where e.house_id is null group by 1 order by 1')
    for year, n in tcur.fetchall():
        log(f'  without_etc created={year}  {n:>9}')

    log(f'--- 本機段抽樣（{SAMPLE} 列 × house/house_ts/house_etc）---')
    tcur.execute('select src_id, dst_id from migrate_house_map where src_id >= %s',
                 [OFFSET])
    remap = dict(tcur.fetchall())

    def compare(table, cols, id_col, ids, map_id=True):
        global failed
        col_list = ', '.join(cols)
        bad = 0
        for lid in ids:
            tid = remap.get(lid + OFFSET, lid + OFFSET) if map_id else lid + OFFSET
            src.execute(f'select {col_list} from {table} where {id_col} = %s', [lid])
            tcur.execute(f'select {col_list} from {table} where {id_col} = %s', [tid])
            s_row, t_row = src.fetchone(), tcur.fetchone()
            if t_row is None or list(s_row) != list(t_row):
                log(f'  !! {table} local {id_col}={lid} → target {tid}: '
                    + ('missing' if t_row is None else 'column mismatch'))
                bad += 1
        if bad:
            failed = True
        log(f'  {table}: {len(ids) - bad}/{len(ids)} OK')

    src.execute('select id from house order by random() limit %s', [SAMPLE])
    compare('house', HOUSE_COLS, 'id', [r[0] for r in src.fetchall()])
    src.execute('select id from house_ts order by random() limit %s', [SAMPLE])
    compare('house_ts', TS_COLS, 'id', [r[0] for r in src.fetchall()], map_id=False)
    src.execute('select house_id from house_etc order by random() limit %s', [SAMPLE])
    compare('house_etc', ETC_COLS, 'house_id', [r[0] for r in src.fetchall()])

    log('recon ' + ('FAILED' if failed else 'OK'))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
