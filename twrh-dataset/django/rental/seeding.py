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
from collections import namedtuple
from datetime import timedelta

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
                 refresh_days=7, fresh_hours=12):
    '''四類 detail seeds（與 gen_diff_seeds 語意逐條對齊）：

    - stale：OPENED ∧ (從未 detail ∨ 距上次 detail ≥ refresh_days)
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

    stale_cut = now - timedelta(days=refresh_days)
    fresh_cut = now - timedelta(hours=fresh_hours)

    stale, fingerprint, fresh = set(), set(), set()
    for hid in open_ids:
        st = state[hid]
        crawled = st.detail_crawled_at
        if crawled is None or crawled < stale_cut:
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


def select_new_seeds(today_stubs, state):
    '''前緣掃描的 seed_mode=new：今日在列 ∧ 從未 detail。'''
    return {hid for hid in latest_fingerprints(today_stubs)
            if hid in state and state[hid].open
            and state[hid].detail_crawled_at is None}
