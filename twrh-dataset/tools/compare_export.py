'''compare_export：兩份 export CSV 的「排序正規化後逐 byte」比對（無 DB）。

S3a 的驗收門檻（2026-09-17 維護者拍板）：同一區間由 DB 路徑與 snapshot 路徑各出
一份 CSV，**以物件編號排序後逐 byte 一致**。不直接比原檔位元組——DB 路徑的列序是
`House.id` 遞減（自增主鍵，parquet 沒有也不該有），snapshot 路徑是物件編號遞減。

一致就 exit 0；不一致列出「只在一邊的戶」與逐欄差異筆數＋樣本，exit 1。

用法（在 twrh-dataset/ 下）：
  poetry run python tools/compare_export.py DB.csv SNAPSHOT.csv [--sample 5] [--key 物件編號]
  poetry run python tools/compare_export.py A.zip B.zip        # 直接吃 export 的 zip
zip 會取其中第一個 *.csv（月包形狀：tw-rental-data/<prefix>-raw.csv）。

已知且刻意的差異（`--expect-mapped` 一併略過）：
  物件首次發現時間（DB=House.created／snapshot=first_seen_at）
  物件最後更新時間（DB=House.updated／snapshot=max(last_seen_at, last_detail_at, crawled_at)）
  刊登者編碼（DB=Author.uuid／snapshot=author_key）
  提供家具_*（DB 被 list 的 tag 版蓋掉＝失真，snapshot 是最後一次 detail 的值＝正確；
    2026-09-18 拍板列為預期差異，但每次印「幾戶兩軌不同」當度量——歸零才奇怪）
  每坪租金（含管理費與停車費）（2026-09-20 維護者確認 best effort、snapshot 為準）：DB 的 list
    pipeline 每個 list 日寫 list 頁的「月租／坪數」（不含費用），下次 detail 又蓋回含費用，
    同一戶在兩公式間輪流；snapshot fold 每個 list 日以新月租＋攜帶的管理費／停車費重算，
    一致符合欄名。exportcheck #2 量到 29,644 戶。
  格局編碼（陽台/衛浴/房/廳）（2026-09-20）：list 頁只給房／廳，list 解析器把陽台／衛浴填 0
    組碼，DB 每個 list 日被蓋成 0000 開頭；snapshot fold 改為攜帶的陽台／衛浴＋list 房／廳重組。
  坪數 的小數位（2026-09-19 exportcheck #1：56 戶）：591 list 頁給 1 位小數、detail 頁給 2 位；
    同一天 detail 之後又被 sweep 的 list 看到時，DB 是後寫者（list、1 位）勝，fold 是同日
    detail 勝（2 位）。snapshot 較精確，不是錯——兩邊各進位到 1 位（HALF_UP）相等就視為
    對映相等，逐 byte 不同也判 IDENTICAL；筆數照印當度量。
'''
import argparse
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import io
import os
import sys
import zipfile

MAPPED_COLUMNS = ['物件首次發現時間', '物件最後更新時間', '刊登者編碼']

# 家具欄：兩軌本來就不該一致，**snapshot 才是對的**（2026-09-18 維護者拍板列為預期差異）。
# DB 的 House.facilities 被 list 日的 tag 版蓋掉（「屋主直租」「近商圈」那種），沒有
# 床／電視／冷氣 的 key，KeyTextTransform 取出來是 NULL → 公開 CSV 整欄失真；
# snapshot 帶的是最後一次 detail 的家具 dict。2026-09-18 首次 exportcheck：3,739 筆
# DB '-' 對 snapshot 有值。schema 1.0 §3.5 與 issue #238 已記這個修復。
# 2026-09-20 加兩欄（見檔頭）：每坪租金＝DB 兩公式輪流、snapshot 一致含費用；格局編碼＝DB 被
# list 日 0000 前綴蓋掉、snapshot 攜帶陽台／衛浴重組。都是 1.0 修 0.x 失真、值會變（schema 1.0 §3.5）
IMPROVED_COLUMNS = ['提供家具_', '每坪租金（含管理費與停車費）', '格局編碼（陽台/衛浴/房/廳）']


def _round1(v):
    # 591 是四捨五入（18.95 → 19.0）；python 的 round() 對 x.x5 走二進位＋銀行家進位
    # 會得 18.9（exportcheck #2 剩 3 戶全是這型），所以走十進位 HALF_UP
    try:
        return Decimal(str(v).strip()).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _ping_equal(a, b):
    # 坪數：DB（list、1 位）vs snapshot（detail、2 位）——各進位到 1 位相等即對映相等
    ra, rb = _round1(a), _round1(b)
    return ra is not None and rb is not None and ra == rb


# 小數位對映（`--expect-mapped` 才套用）：欄名 → 相等判準；不相等的照常計入 DIFF
TOLERANT_COLUMNS = {
    '坪數': _ping_equal,
}


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
                    help='略過三個已知改對映的欄＋修正欄（家具／每坪租金／格局編碼；1.0 修 0.x 失真）'
                         '＋坪數小數位對映')
    args = ap.parse_args()

    left, right = read_csv(args.left), read_csv(args.right)
    lh, rh = left[0], right[0]
    if lh != rh:
        only_l = [c for c in lh if c not in rh]
        only_r = [c for c in rh if c not in lh]
        sys.exit('!!! 欄位不同：只在左 {} ／只在右 {}'.format(only_l, only_r))

    key_idx = lh.index(args.key)
    drop_idx = set()
    if args.expect_mapped:
        drop_idx = {lh.index(c) for c in MAPPED_COLUMNS if c in lh}
        drop_idx |= {i for i, c in enumerate(lh)
                     if any(c.startswith(p) for p in IMPROVED_COLUMNS)}

    # 被略過的欄不能完全不看：兩軌對映不同但「值在不在」要對得上——2026-09-17 實測
    # 若「物件最後更新時間」只取 max(last_seen_at, last_detail_at)，九月窗有 31.5% 的
    # 列會變 '-'（#11 回填的 9/1–9/10 沒有這兩欄），而逐 byte 比對正好略過它、看不見
    mapped_idx = sorted(i for i in drop_idx if lh[i] in MAPPED_COLUMNS)
    for name, rows in (('left', left[1:]), ('right', right[1:])):
        if not mapped_idx or not rows:
            break
        stats = ['{}={:.2%}'.format(lh[i], sum(1 for r in rows if r[i] == '-') / len(rows))
                 for i in mapped_idx]
        print('{} 略過欄的 "-" 比率: {}'.format(name, '、'.join(stats)))
    # 家具欄不比 byte，但筆數要印出來——它是「snapshot 修好了 DB 的失真」的度量，
    # 歸零才奇怪（代表 clobber 沒發生或 snapshot 也被蓋到）
    improved = [i for i in drop_idx if lh[i] not in MAPPED_COLUMNS]
    if improved:
        lmap0 = {r[key_idx]: r for r in left[1:]}
        n_diff = {p: 0 for p in IMPROVED_COLUMNS}
        for hid, rrow in ((r[key_idx], r) for r in right[1:]):
            lrow = lmap0.get(hid)
            if not lrow:
                continue
            for p in IMPROVED_COLUMNS:
                if any(lrow[i] != rrow[i] for i in improved if lh[i].startswith(p)):
                    n_diff[p] += 1
        print('修正欄（預期差異，snapshot 為準）: {}'.format('、'.join(
            '{} {} 戶'.format(p.rstrip('_'), n) for p, n in n_diff.items())))

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

    tolerant = {lh.index(c): fn for c, fn in TOLERANT_COLUMNS.items()
                if args.expect_mapped and c in lh}
    counts = {}
    samples = {}
    tolerated = {}
    for hid in sorted(set(lmap) & set(rmap)):
        for i, (a, b) in enumerate(zip(lmap[hid], rmap[hid])):
            if a == b or i in drop_idx:
                continue
            col = lh[i]
            if i in tolerant and tolerant[i](a, b):
                tolerated[col] = tolerated.get(col, 0) + 1
                continue
            counts[col] = counts.get(col, 0) + 1
            samples.setdefault(col, []).append((hid, a, b))
    if tolerated:
        print('小數位對映（預期差異，snapshot 為準）: {}'.format('、'.join(
            '{} {} 戶'.format(col, n) for col, n in sorted(tolerated.items()))))
    if not only_l and not only_r and not counts:
        print('IDENTICAL — 逐 byte 不同，但差異全在小數位對映內')
        return 0

    print('DIFF — 只在左 {} 戶、只在右 {} 戶、共有 {} 戶'.format(
        len(only_l), len(only_r), len(set(lmap) & set(rmap))))
    if only_l:
        print('  只在左樣本: {}'.format(only_l[:args.sample]))
    if only_r:
        print('  只在右樣本: {}'.format(only_r[:args.sample]))
    if counts:
        print('  逐欄差異（欄位: 筆數）：')
        for col, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print('    {:<30} {:>7}  例 {}'.format(
                col, n, samples[col][:args.sample]))
    return 1


if __name__ == '__main__':
    sys.exit(main())
