'''compare_parsed：兩組 parsed parquet 逐欄比（無 DB）。

用途：
- 4b 驗收：pipeline 產的分區檔 vs `rerun_from_raws --parquet-dir` 從同日 raw 日包
  重放的結果——同一 parser 版本應逐欄一致（parser 決定性＋重放路徑正確）
- 修 parser 後：新舊版本重放結果 diff，看改動只碰到預期欄位

用法（在 twrh-dataset/ 下）：
  poetry run python tools/compare_parsed.py A_DIR_OR_FILE B_DIR_OR_FILE [--sample 5]
目錄＝其下所有 *.parquet（遞迴）。每戶各取 crawled_at 最晚一列，只比兩邊都有的戶；
忽略 run／date／crawled_at／parser_version 之外的來源欄。有欄位不一致 exit 1。
'''
import argparse
import glob
import json
import math
import os
import sys

import pyarrow.parquet as pq

IGNORE = {'run', 'date', 'crawled_at', 'parser_version', 'parsed_version'}


def load(path):
    files = [path] if os.path.isfile(path) else sorted(
        glob.glob(os.path.join(path, '**', '*.parquet'), recursive=True))
    latest = {}
    for f in files:
        for row in pq.read_table(f).to_pylist():
            hid = row['vendor_house_id']
            key = row.get('crawled_at')
            if hid not in latest or (key or '') >= (latest[hid].get('crawled_at') or ''):
                latest[hid] = row
    return files, latest


def equal(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-6)
    return a == b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('a')
    ap.add_argument('b')
    ap.add_argument('--sample', type=int, default=5)
    opt = ap.parse_args()
    files_a, rows_a = load(opt.a)
    files_b, rows_b = load(opt.b)
    common = sorted(set(rows_a) & set(rows_b))
    mismatch, samples = {}, {}
    same = 0
    for hid in common:
        ra, rb = rows_a[hid], rows_b[hid]
        ok = True
        for name in sorted(set(ra) | set(rb)):
            if name in IGNORE:
                continue
            if not equal(ra.get(name), rb.get(name)):
                ok = False
                mismatch[name] = mismatch.get(name, 0) + 1
                if len(samples.setdefault(name, [])) < opt.sample:
                    samples[name].append((hid, ra.get(name), rb.get(name)))
        same += ok
    print(json.dumps({
        'a_files': len(files_a), 'b_files': len(files_b),
        'a_houses': len(rows_a), 'b_houses': len(rows_b),
        'common': len(common), 'identical': same,
        'only_a': len(set(rows_a) - set(rows_b)), 'only_b': len(set(rows_b) - set(rows_a)),
        'mismatch_by_field': mismatch,
    }, ensure_ascii=False, default=str))
    for name, items in samples.items():
        print('{}: {}'.format(name, items))
    sys.exit(1 if mismatch else 0)


if __name__ == '__main__':
    main()
