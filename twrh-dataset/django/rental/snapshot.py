'''snapshot 摺疊（Phase 4c；architecture-roadmap〈snapshot 即摺疊狀態〉）。

    today = fold(yesterday_snapshot, today_stubs, today_parsed, today_deal_events, date)

每日每戶一列，欄位＝parsed 全欄＋carry 欄（contracts.SNAPSHOT_FIELDS）。一階遞迴：
新環境冷啟只需昨日一份 snapshot。取代 synthts（合成被 skip 物件的當日列）與
House（現值＝最新 snapshot）。

規則（與現制 pipeline／synthts／syncstateful 語意逐條對齊）：
- 在 list：last_fingerprint＝最後一次 stub 指紋
- 今日有 detail（parsed）：整列覆蓋，source='detail'，last_detail_at＝crawled_at，
  fingerprint_at_last_detail＝last_fingerprint（今日在 list 就是今日的，否則是最後已知的）
- 只在 list：list 給的欄位（價格／格局…）覆蓋、其餘沿用昨日，source='list'
- 都沒有：整列沿用昨日，source='carry'，days_absent+1
- 在 list：last_seen_at＝最後 seen_at、days_absent=0；first_seen_at 只在首見時設
- DEAL sticky：昨日 DEAL 不被 NOT_FOUND 覆寫（Issue #9）；deals 事件（vendor 給
  deal_time／n_day_deal）永遠勝，deal_source='deals'；detail 回 NOT_FOUND 且
  昨日非 DEAL → NOT_FOUND（推導型成交留給下游，deal_source 不設）
- 已關閉（NOT_FOUND／DEAL）且今日無任何訊號的戶：不再攜帶（snapshot 只含
  當日仍有意義的列＝OPENED 或今日有事件），與現制 HouseTS「open 每日一列」一致

不 import Django。
'''
from rental import contracts

OPENED, NOT_FOUND, DEAL = 0, 1, 2   # rental.enums.DealStatusType 的整數值（只增不改）

_LIST_FIELDS = [name for name, _ in contracts.LIST_STUB_FIELDS
                if name not in ('vendor', 'vendor_house_id', 'date', 'run',
                                'seen_at', 'fingerprint', 'stub_version')]
_PARSED_COPY = [name for name, _ in contracts.PARSED_FIELDS
                if name not in ('vendor', 'vendor_house_id', 'date', 'run', 'parsed_version')]


def _latest(rows, key='crawled_at'):
    out = {}
    for row in rows:
        hid = row['vendor_house_id']
        stamp = row.get(key) or ''
        stamp = stamp.isoformat() if hasattr(stamp, 'isoformat') else stamp
        if hid not in out or stamp >= out[hid][0]:
            out[hid] = (stamp, row)
    return {hid: row for hid, (_s, row) in out.items()}


def _blank(vendor, hid, date_str):
    row = {name: None for name, _ in contracts.SNAPSHOT_FIELDS}
    row.update({'vendor': vendor, 'vendor_house_id': hid, 'date': date_str,
                'deal_status': OPENED, 'days_absent': 0,
                'snapshot_version': contracts.SNAPSHOT_VERSION})
    return row


def fold(prev_rows, stubs, parsed_rows, deal_events, date_str, vendor='591'):
    '''回傳今日 snapshot 列（list of dict，依 vendor_house_id 排序）。'''
    prev = {r['vendor_house_id']: r for r in prev_rows}
    stub_by = _latest(stubs, 'seen_at')
    parsed_by = _latest(parsed_rows, 'crawled_at')
    deal_by = _latest(deal_events, 'seen_at')

    out = []
    for hid in sorted(set(prev) | set(stub_by) | set(parsed_by) | set(deal_by)):
        yesterday = prev.get(hid)
        stub = stub_by.get(hid)
        parsed = parsed_by.get(hid)
        deal = deal_by.get(hid)
        touched = stub is not None or parsed is not None or deal is not None
        if yesterday is not None and yesterday['deal_status'] != OPENED and not touched:
            continue   # 已關閉且無新訊號：不再攜帶

        row = _blank(vendor, hid, date_str)
        if yesterday is not None:
            row.update({k: yesterday.get(k) for k in row if k not in ('date', 'snapshot_version')})
        row['source'] = 'carry'

        if stub is not None and stub.get('fingerprint'):
            row['last_fingerprint'] = stub['fingerprint']

        if parsed is not None:
            for name in _PARSED_COPY:
                if name in parsed:
                    row[name] = parsed[name]
            row['source'] = 'detail'
            row['last_detail_at'] = parsed.get('crawled_at')
            row['fingerprint_at_last_detail'] = row.get('last_fingerprint')
            if parsed.get('deal_status') == NOT_FOUND and yesterday is not None \
                    and yesterday['deal_status'] == DEAL:
                # Issue #9：DEAL sticky——不被 NOT_FOUND 回滾
                for k in ('deal_status', 'deal_time', 'n_day_deal', 'deal_source'):
                    row[k] = yesterday.get(k)
        elif stub is not None:
            for name in _LIST_FIELDS:
                if stub.get(name) is not None:
                    row[name] = stub[name]
            row['source'] = 'list'

        if stub is not None:
            row['last_seen_at'] = stub.get('seen_at')
            row['days_absent'] = 0
            if row.get('first_seen_at') is None:
                row['first_seen_at'] = stub.get('seen_at')
        elif yesterday is not None:
            row['days_absent'] = (yesterday.get('days_absent') or 0) + 1

        if deal is not None:
            # vendor 的成交事件永遠勝（#229 deals stage）
            row['deal_status'] = DEAL
            row['deal_time'] = deal.get('deal_time')
            row['n_day_deal'] = deal.get('n_day_deal')
            row['deal_source'] = 'deals'
        elif row['deal_status'] == DEAL and row.get('deal_source') is None:
            row['deal_source'] = 'inferred'

        out.append(row)
    return out
