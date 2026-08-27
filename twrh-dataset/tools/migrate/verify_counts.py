"""遷移對帳：各表 row count、house_etc 抽樣欄位比對＋raw 確實為 NULL。"""
import random
import sys

from common import load_django, log, source_cursor, target_conn

load_django()

TABLES = ['vendor', 'sub_region', 'rental_author', 'crawlerrequest_stats',
          'region_ts', 'house', 'house_ts', 'house_etc']
SAMPLE = 50
COMPARE_COLS = ('created', 'updated', 'vendor_house_id', 'detail_dict',
                'could_be_rooftop', 'vendor_id')


def main():
    src = source_cursor()
    target = target_conn()
    tcur = target.cursor()
    failed = False

    log('--- row counts (source vs target) ---')
    for t in TABLES:
        src.execute(f'select count(*) from "{t}"')
        tcur.execute(f'select count(*) from "{t}"')
        s, g = src.fetchone()[0], tcur.fetchone()[0]
        flag = 'OK' if s == g else '!! MISMATCH'
        if s != g:
            failed = True
        log(f'  {t:24s} {s:>9} vs {g:>9}  {flag}')

    log(f'--- house_etc sampling ({SAMPLE} rows) ---')
    tcur.execute('select house_id from house_etc')
    ids = [r[0] for r in tcur.fetchall()]
    cols = ', '.join(COMPARE_COLS)
    for hid in random.sample(ids, min(SAMPLE, len(ids))):
        src.execute(f'select {cols} from house_etc where house_id=%s', [hid])
        tcur.execute(f'select {cols}, detail_raw, list_raw '
                     'from house_etc where house_id=%s', [hid])
        s_row, t_row = src.fetchone(), tcur.fetchone()
        if list(s_row) != list(t_row[:len(COMPARE_COLS)]):
            log(f'  !! house_id {hid}: column mismatch')
            failed = True
        if t_row[-1] is not None or t_row[-2] is not None:
            log(f'  !! house_id {hid}: raw not stripped')
            failed = True
    log('sampling ' + ('FAILED' if failed else 'OK'))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
