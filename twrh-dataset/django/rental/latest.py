'''全戶最新狀態總表（Phase 4 S3c；architecture-roadmap 切換階梯表「S3c」列，2026-09-15 拍板）。

    latest(D) = fold(latest(D−1), final_snapshot(D))

一檔「每戶最後已知狀態」parquet，遞推：以當日 **final** snapshot 逐戶覆蓋前一日總表；
snapshot 裡沒有的戶（已關閉且無新訊號、不再攜帶）由總表接住、原列不動。只吃 final、
落後一天。欄位＝snapshot 全欄**減 vendor_extra**（1 GB 級，留在 parsed／snapshot 分區）；
`date` 沿用來源 snapshot 的日期，就是這列的 as-of。

角色：S6 去 Django 時接替 DB House（現值＝最新 snapshot 疊加歷史），export 改讀它；
fold 的「recovered from earlier snapshots」（關閉多日後才進成交列表的戶）改查它，
不必回頭掃 lookback 天的 snapshot。

檔案佈局（artifacts 樹 `latest/<vendor>/`）：每日 append 一個 delta 檔（＝當日 final
snapshot 去掉 vendor_extra，8 萬列、幾 MB）、每月 1 日壓成新 base 兼檢查點（月檢查點
永久；日檔與 noncurrent version 在 s3.tf 掛只針對此前綴的 7 天 lifecycle）。修壞掉的某
天＝從上個月檢查點順序重放 ≤31 份 snapshot。

dry-run 校驗對照＝S2b archive 的 `public.house` parquet（2026-09-18 拍板；不對 DB House，
S5 destroy 之後仍能重做）：tools/latest_dryrun.py。

不 import Django。
'''
from rental import contracts

LATEST_FIELDS = [f for f in contracts.SNAPSHOT_FIELDS if f[0] != 'vendor_extra']
LATEST_VERSION = 1
_NAMES = [name for name, _ in LATEST_FIELDS]


def strip(row):
    '''snapshot 列 → 總表列（只留 LATEST_FIELDS；缺的 key 補 None）。'''
    return {name: row.get(name) for name in _NAMES}


def fold(prev_rows, snapshot_rows):
    '''回傳新總表列（list of dict，依 vendor_house_id 排序）。

    snapshot 有的戶：整列覆蓋（snapshot 列本身已是該戶當日摺疊後的完整狀態，含 carry 欄）；
    snapshot 沒有的戶：沿用前一日總表那列（as-of 不變）。同一份 snapshot 內一戶一列，
    多列時取 date 最晚、再取 last_seen_at／last_detail_at 最晚的一列（防呆，正常不會發生）。
    '''
    latest = {r['vendor_house_id']: r for r in prev_rows}
    for row in snapshot_rows:
        hid = row['vendor_house_id']
        cur = latest.get(hid)
        new = strip(row)
        if cur is not None and cur.get('date') == new.get('date'):
            # 同日兩列：留觀測較晚的那列
            if _order_key(cur) > _order_key(new):
                continue
        latest[hid] = new
    return [latest[hid] for hid in sorted(latest)]


def _order_key(row):
    return (row.get('date') or '', str(row.get('last_detail_at') or ''),
            str(row.get('last_seen_at') or ''))


def delta(snapshot_rows):
    '''當日 delta 檔內容＝當日 final snapshot 去掉 vendor_extra（每列都算變動：
    carry 列的 days_absent 也每天 +1），依 vendor_house_id 排序。'''
    return sorted((strip(r) for r in snapshot_rows), key=lambda r: r['vendor_house_id'])
