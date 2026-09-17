'''compare_export：兩份 export CSV 的「排序正規化後逐 byte」比對（無 DB）。

S3a 的驗收門檻（2026-09-17 維護者拍板）：同一區間由 DB 路徑與 snapshot 路徑各出
一份 CSV，**以物件編號排序後逐 byte 一致**。不直接比原檔位元組——DB 路徑的列序是
`House.id` 遞減（自增主鍵，parquet 沒有也不該有），snapshot 路徑是物件編號遞減。

一致就 exit 0；不一致列出「只在一邊的戶」與逐欄差異筆數＋樣本，exit 1。

用法（在 twrh-dataset/ 下）：
  poetry run python tools/compare_export.py DB.csv SNAPSHOT.csv [--sample 5] [--key 物件編號]
  poetry run python tools/compare_export.py A.zip B.zip        # 直接吃 export 的 zip
zip 會取其中第一個 *.csv（月包形狀：tw-rental-data/<prefix>-raw.csv）。

已知且刻意的差異（三欄，2026-09-17 拍板；用 --expect-mapped 一併略過）：
  物件首次發現時間（DB=House.created／snapshot=first_seen_at）
  物件最後更新時間（DB=House.updated／snapshot=max(last_seen_at, last_detail_at)）
  刊登者編碼（DB=Author.uuid／snapshot=author_key）
'''
import argparse
import csv
import hashlib
import io
import os
import sys
import zipfile

MAPPED_COLUMNS = ['物件首次發現時間', '物件最後更新時間', '刊登者編碼']


def read_csv(path):
    if path.lower().endswith('.zip'):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith('.csv')]
            if not names:
                sys.exit('!!! {} 裡沒有 csv'.format(path))
            with zf.open(sorted(names)[0]) as fh:
                text = io.TextIOWrapper(fh, encoding='utf-8', newline='')
                return list(csv.reader(text))
    with open(path, newline='') as fh:
        return list(csv.reader(fh))


def normalized_bytes(header, rows, key_idx, drop_idx):
    keep = [i for i in range(len(header)) if i not in drop_idx]
    buf = io.StringIO(newline='')
    writer = csv.writer(buf)
    writer.writerow([header[i] for i in keep])
    for row in sorted(rows, key=lambda r: r[key_idx]):
        writer.writerow([row[i] for i in keep])
    return buf.getvalue().encode('utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('left', help='DB 路徑那份（csv 或 zip）')
    ap.add_argument('right', help='snapshot 路徑那份（csv 或 zip）')
    ap.add_argument('--key', default='物件編號')
    ap.add_argument('--sample', type=int, default=5)
    ap.add_argument('--expect-mapped', action='store_true',
                    help='略過三個已知改對映的欄（S3a 過渡期）')
    args = ap.parse_args()

    left, right = read_csv(args.left), read_csv(args.right)
    lh, rh = left[0], right[0]
    if lh != rh:
        only_l = [c for c in lh if c not in rh]
        only_r = [c for c in rh if c not in lh]
        sys.exit('!!! 欄位不同：只在左 {} ／只在右 {}'.format(only_l, only_r))

    key_idx = lh.index(args.key)
    drop_idx = {lh.index(c) for c in MAPPED_COLUMNS if args.expect_mapped and c in lh}

    lb = normalized_bytes(lh, left[1:], key_idx, drop_idx)
    rb = normalized_bytes(rh, right[1:], key_idx, drop_idx)
    print('left  {} 列 sha1 {}'.format(len(left) - 1, hashlib.sha1(lb).hexdigest()))
    print('right {} 列 sha1 {}'.format(len(right) - 1, hashlib.sha1(rb).hexdigest()))
    if drop_idx:
        print('（略過已知改對映欄：{}）'.format('、'.join(
            lh[i] for i in sorted(drop_idx))))
    if lb == rb:
        print('IDENTICAL — 排序正規化後逐 byte 一致')
        return 0

    lmap = {r[key_idx]: r for r in left[1:]}
    rmap = {r[key_idx]: r for r in right[1:]}
    only_l = sorted(set(lmap) - set(rmap))
    only_r = sorted(set(rmap) - set(lmap))
    print('DIFF — 只在左 {} 戶、只在右 {} 戶、共有 {} 戶'.format(
        len(only_l), len(only_r), len(set(lmap) & set(rmap))))
    if only_l:
        print('  只在左樣本: {}'.format(only_l[:args.sample]))
    if only_r:
        print('  只在右樣本: {}'.format(only_r[:args.sample]))

    counts = {}
    samples = {}
    for hid in sorted(set(lmap) & set(rmap)):
        for i, (a, b) in enumerate(zip(lmap[hid], rmap[hid])):
            if a == b or i in drop_idx:
                continue
            col = lh[i]
            counts[col] = counts.get(col, 0) + 1
            samples.setdefault(col, []).append((hid, a, b))
    if counts:
        print('  逐欄差異（欄位: 筆數）：')
        for col, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print('    {:<30} {:>7}  例 {}'.format(
                col, n, samples[col][:args.sample]))
    return 1


if __name__ == '__main__':
    sys.exit(main())
