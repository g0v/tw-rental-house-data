'''detail seed 推導＝純函數（Phase 4a；architecture-roadmap〈L-C 案例對照〉）。

現制 `Detail591Spider.gen_diff_seeds` 把四類判準散在三處 DB 狀態
（House 欄位、HouseTS 當日／昨日 list 列、RequestTS）。這裡改成

    select_seeds(今日 stubs, 昨日 stubs, 每戶狀態, now) → 四類 seeds

不 import Django：fixture 檔即可測邊界（離線可測）、對任一歷史日重算
即重現當天決策（可稽核）、任何 vendor 的 parse_list 產得出帶指紋的
stub 就自動獲得整套機制（多 vendor 免費）。

每戶狀態（HouseState）過渡期由 DB 欄位轉接（seedcheck），4c 起改讀
昨日 snapshot 的 carry 欄：last_detail_at／fingerprint_at_last_detail／
days_absent／last_seen_at。兩者語意對齊——`fingerprint_at_last_detail`
有值時用它比今日指紋；沒有（過渡期）就退回 `fingerprint_changed_at >
detail_crawled_at` 的舊判準。
'''
import hashlib
import json
import os
from collections import namedtuple
from datetime import datetime, timedelta

HouseState = namedtuple('HouseState', [
    'open',                        # deal_status == OPENED
    'detail_crawled_at',           # 上次 detail 成功解析（None＝從未）
    'fingerprint_at_last_detail',  # 4c carry 欄；過渡期 None
    'fingerprint_changed_at',      # 舊制 House.list_fingerprint_changed_at
])
HouseState.__new__.__defaults__ = (False, None, None, None)

SeedResult = namedtuple('SeedResult', [
    'stale', 'fingerprint', 'absent', 'returned', 'seeds',
    'n_open', 'n_in_list', 'skipped'])


def seed_stamp_path(day):
    '''DB 生種子時留的 stamp：`logs/progress/<date>.seed.json`（與 persist_queue 的
    progress 檔同目錄＝repo 根的 logs/）。內容＝spider 算 stale 用的 `now` 與四類計數。
    seedcheck 讀它把「現在」釘在同一刻——釘 RequestTS.created 仍晚幾分鐘
    （查詢在 now 之後跑），N 天前那幾分鐘內 detail 過的戶就被純函數多判 stale
    （2026-09-12：only_pure 23、全在 stale 類）。'''
    root = os.environ.get('TWRH_PROGRESS_DIR') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'logs', 'progress')
    return os.path.join(root, '{}.seed.json'.format(day.isoformat()))


def write_seed_stamp(day, now, classes, n_seeds):
    path = seed_stamp_path(day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump({'now': now.isoformat(),
                   'classes': dict(classes), 'seeds': n_seeds}, f, ensure_ascii=False)
    return path


def read_seed_stamp(day):
    '''回 (now: aware datetime, stamp dict)；沒有 stamp 回 (None, None)。'''
    path = seed_stamp_path(day)
    if not os.path.exists(path):
        return None, None
    with open(path) as f:
        stamp = json.load(f)
    return datetime.fromisoformat(stamp['now']), stamp


def refresh_days_for(house_id, refresh_days, jitter_days=0):
    '''per-house 的 stale 門檻天數：refresh_days ± jitter，由 house_id 雜湊決定、
    永遠一致。用途＝攤平「同一天全量 bootstrap → 7 天後同一天全部到期」的回波
    （2026-09-10 實踩：detail 43,827 vs 平常 7,300）。jitter=0 即舊制。'''
    if not jitter_days:
        return refresh_days
    bucket = int(hashlib.sha1(str(house_id).encode('utf-8')).hexdigest()[:8], 16)
    return refresh_days + bucket % (2 * jitter_days + 1) - jitter_days


def is_stale(house_id, detail_crawled_at, now, refresh_days, jitter_days=0):
    if detail_crawled_at is None:
        return True
    return detail_crawled_at < now - timedelta(
        days=refresh_days_for(house_id, refresh_days, jitter_days))


def latest_fingerprints(stubs):
    '''stub 列 → {house_id: 當日最後一次觀測的指紋}（同日多輪取最晚 seen_at）。'''
    seen = {}
    for stub in stubs:
        hid = stub['vendor_house_id']
        at = stub.get('seen_at') or ''
        if hid not in seen or at >= seen[hid][0]:
            seen[hid] = (at, stub.get('fingerprint'))
    return {hid: fp for hid, (_at, fp) in seen.items()}


def select_seeds(today_stubs, yesterday_ids, state, now,
                 refresh_days=7, fresh_hours=12, refresh_jitter_days=0):
    '''四類 detail seeds（與 gen_diff_seeds 語意逐條對齊）：

    - stale：OPENED ∧ (從未 detail ∨ 距上次 detail ≥ refresh_days ± jitter（per-house 雜湊））
    - fingerprint：OPENED ∧ detail 過 ∧ 在今日 list ∧ 指紋自上次 detail 後變了
    - absent：OPENED ∧ 不在今日 list ∧ 不在昨日 list（連續 ≥2 天缺席）
    - returned：OPENED ∧ 在今日 list ∧ 不在昨日 list ∧ 本輪未 detail（fresh_hours）

    today_stubs：今日 stub 列（iterable of dict）；yesterday_ids：昨日在列的
    house_id 集合（昨日 stub 檔算出，或過渡期由 HouseTS 轉接）；
    state：{house_id: HouseState}；now：aware datetime。
    '''
    today_fp = latest_fingerprints(today_stubs)
    in_list_today = set(today_fp)
    in_list_yesterday = set(yesterday_ids)
    open_ids = {hid for hid, st in state.items() if st.open}

    fresh_cut = now - timedelta(hours=fresh_hours)

    stale, fingerprint, fresh = set(), set(), set()
    for hid in open_ids:
        st = state[hid]
        crawled = st.detail_crawled_at
        if is_stale(hid, crawled, now, refresh_days, refresh_jitter_days):
            stale.add(hid)
        if crawled is not None and crawled >= fresh_cut:
            fresh.add(hid)
        if crawled is not None and hid in in_list_today:
            if st.fingerprint_at_last_detail is not None:
                changed = today_fp[hid] != st.fingerprint_at_last_detail
            else:
                changed = (st.fingerprint_changed_at is not None
                           and st.fingerprint_changed_at > crawled)
            if changed:
                fingerprint.add(hid)

    absent = open_ids - in_list_today - in_list_yesterday
    returned = ((open_ids & in_list_today) - in_list_yesterday) - fresh
    seeds = stale | fingerprint | absent | returned
    skipped = len(open_ids & in_list_today) - len(seeds & in_list_today)
    return SeedResult(stale, fingerprint, absent, returned, seeds,
                      len(open_ids), len(in_list_today), skipped)


def seeds_from_files(short, day, now, refresh_days=7, refresh_jitter_days=0, bucket=None):
    '''S1：整套判準走檔案——今日 list stub 分區＋昨日 snapshot 的 carry 欄，不碰 DB。

    回傳 `(SeedResult, meta)`；**材料不齊時回 `(None, meta)`**（meta['reason'] 說明），
    由呼叫端決定退路（spider 退回 DB 判準）。刻意不自己找替代來源：種子算錯的代價是
    整天漏抓或整天重抓，寧可退回已知可用的那條路。

    兩個材料的要求：
    - 今日 stub 必須存在（4a 的 liststubs stage 在 seed 之前）
    - **昨日必須有「全量 run」的 stub 分區**才拿它當「昨日在列」：sweep 只掃前緣，
      拿子集當昨日在列會把幾乎全部判成回列／缺席（2026-09-10 4a 首日實踩：
      only_pure 26,161 全是這兩類）
    - 昨日 snapshot 必須存在（狀態來源）

    `now` 由呼叫端給並寫進 seed stamp，seedcheck 釘同一刻（見 seed_stamp_path）。
    '''
    from rental import artifacts   # 延後 import：本模組要能離線測、不拖 pyarrow／boto3
    day_str = day.isoformat()
    yesterday = day - timedelta(days=1)
    y_str = yesterday.isoformat()

    today_stubs = list(artifacts.read_list_stubs(short, day_str, bucket))
    if not today_stubs:
        return None, {'reason': 'no list stubs for {}'.format(day_str)}

    y_files = artifacts.list_partition_files(short, y_str, bucket)
    if not any(os.path.basename(f).startswith('run.') for f in y_files):
        return None, {'reason': 'no full-run list partition for {}'.format(y_str)}
    y_stubs = list(artifacts.read_list_stubs(short, y_str, bucket))
    if not y_stubs:
        return None, {'reason': 'yesterday stubs empty for {}'.format(y_str)}
    yesterday_ids = set(latest_fingerprints(y_stubs))

    rows = artifacts.read_snapshot(short, y_str, bucket)
    if not rows:
        return None, {'reason': 'no snapshot for {}'.format(y_str)}
    state = state_from_snapshot(rows, seen_today=latest_fingerprints(today_stubs))

    result = select_seeds(today_stubs, yesterday_ids, state, now,
                          refresh_days=refresh_days,
                          refresh_jitter_days=refresh_jitter_days)
    return result, {'stubs': len(today_stubs), 'yesterday_ids': len(yesterday_ids),
                    'snapshot_rows': len(rows), 'state': len(state)}


def select_new_seeds(today_stubs, state):
    '''前緣掃描的 seed_mode=new：今日在列 ∧ 從未 detail。'''
    return {hid for hid in latest_fingerprints(today_stubs)
            if hid in state and state[hid].open
            and state[hid].detail_crawled_at is None}


OPENED = 0   # enums.DealStatusType.OPENED；這裡不 import Django


def state_from_snapshot(rows, seen_today=()):
    '''S1：{house_id: HouseState}，狀態取自昨日 snapshot 的 carry 欄，不碰 DB。

    對照過渡期的 DB 轉接（seedcheck 從 House 組）：
      open                        ← deal_status == OPENED
      detail_crawled_at           ← last_detail_at
      fingerprint_at_last_detail  ← 同名 carry 欄
      fingerprint_changed_at      ← 不需要。它是 carry 欄還沒有時的退路
                                    （House.list_fingerprint_changed_at），
                                    snapshot 直接給得出指紋本身，走主判準即可。

    只收 OPENED：select_seeds 四類都先交集 open_ids，非 OPENED 載了也用不到，
    而且 snapshot 一天就是全戶一列（含已關閉），全收會把記憶體吃掉
    ——同 seedcheck 2026-09-11 那次 OOM 的教訓。

    seen_today：今日在 list 的 house_id。fold 對「已關閉且今日無訊號」的戶
    不再攜帶（snapshot.py 刻意的設計，否則檔案無限長大），所以關閉後掉出、
    之後又重新上架的戶，昨日 snapshot 裡沒有它——而 DB 軌的 House 永遠在，
    照樣排種子。2026-09-17 dry-run 實測：785 戶只有 DB 軌排、全是這個形狀
    （in_list_today=True、昨日 snapshot 查無此戶）。

    這裡的規則：**今天出現在 list、而我們手上沒有它的狀態 → 當「在架、從未
    detail」**，於是判 stale、排一次。語意上嚴格正確，且只可能多排不可能少排；
    多排也是一次性的（今天抓到就有 parsed 列，明天就回到 snapshot 裡）。

    這不取代 S3c 總表——export 完整性與「每戶最後已知狀態」仍然要它，
    只是 S1 不必等它。'''
    state = {}
    for row in rows:
        if row.get('deal_status') != OPENED:
            continue
        state[row['vendor_house_id']] = HouseState(
            open=True,
            detail_crawled_at=row.get('last_detail_at'),
            fingerprint_at_last_detail=row.get('fingerprint_at_last_detail'),
        )
    for hid in seen_today:
        if hid not in state:
            state[hid] = HouseState(open=True)
    return state
