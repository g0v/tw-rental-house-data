'''snapshot 摺疊（Phase 4c；architecture-roadmap〈snapshot 即摺疊狀態〉）。

    today = fold(yesterday_snapshot, today_stubs, today_parsed, today_deal_events, date)

每日每戶一列，欄位＝parsed 全欄＋carry 欄（contracts.SNAPSHOT_FIELDS）。一階遞迴：
新環境冷啟只需昨日一份 snapshot。取代 synthts（合成被 skip 物件的當日列）與
House（現值＝最新 snapshot）。

規則（與現制 pipeline／synthts／syncstateful 語意逐條對齊）：
- 在 list：last_fingerprint＝最後一次 stub 指紋
- 今日有 detail（parsed）：整列覆蓋，source='detail'，last_detail_at＝crawled_at，
  fingerprint_at_last_detail＝last_fingerprint（今日在 list 就是今日的，否則是最後已知的）
- 今日 detail 是 404／拒解析（parsed 列只帶 deal_status=NOT_FOUND、其餘 NULL）：只當
  狀態訊號——deal_status 改 NOT_FOUND（DEAL sticky 照舊），租金／座標等沿用最後已知值，
  source／last_detail_at 不動（DB 的 detail_crawled_at 也不因 404 更新）。關閉當天那列
  保留最後已知狀態，與 synthts 補齊關閉／成交列同形（2026-09-12 拍板）
- 只在 list：list 給的欄位（價格／格局…）覆蓋、其餘沿用昨日，source='list'
- 都沒有：整列沿用昨日，source='carry'，days_absent+1
- 在 list：last_seen_at＝最後 seen_at、days_absent=0；first_seen_at 只在首見時設
- DEAL sticky：昨日 DEAL 不被 NOT_FOUND 覆寫（Issue #9）；deals 事件（vendor 給
  deal_time／n_day_deal）永遠勝，deal_source='deals'；detail 回 NOT_FOUND 且
  昨日非 DEAL → NOT_FOUND（推導型成交留給下游，deal_source 不設）
- 已關閉（NOT_FOUND／DEAL）且今日無任何訊號的戶：不再攜帶（snapshot 只含
  當日仍有意義的列＝OPENED 或今日有事件），與現制 HouseTS「open 每日一列」一致
- 關閉多日後才進 591 成交列表的戶（591 成交後數日仍補列）：昨日 snapshot 已無此戶，
  呼叫端可把「近幾天 snapshot 裡最後一列」用 closed_rows 傳進來當昨日列，成交列才帶得出
  租金／座標等最後已知值（4d 推導側；沒給就退回只帶成交欄的空白列＝snapshotcheck 的
  deal_only_rows）。days_absent 依兩列日期差遞推。
- 成交段語意（deals 事件勝、inferred、n_day_deal 推導）在 rental/deals.py

不 import Django。
'''
from datetime import date as date_cls

from rental import contracts, deals

OPENED, NOT_FOUND, DEAL = 0, 1, 2   # rental.enums.DealStatusType 的整數值（只增不改）

_LIST_FIELDS = [name for name, _ in contracts.LIST_STUB_FIELDS
                if name not in ('vendor', 'vendor_house_id', 'date', 'run',
                                'seen_at', 'fingerprint', 'stub_version')]
_PARSED_COPY = [name for name, _ in contracts.PARSED_FIELDS
                if name not in ('vendor', 'vendor_house_id', 'date', 'run', 'parsed_version')]
_CLOSURE_BLANK = [name for name in _PARSED_COPY
                  if name not in ('deal_status', 'crawled_at', 'parser_version')]


def is_closure_row(parsed):
    '''pipeline 對 detail 404／拒解析寫的 parsed 列：只帶 deal_status=NOT_FOUND，其餘 NULL。'''
    return parsed.get('deal_status') == NOT_FOUND and \
        all(parsed.get(name) is None for name in _CLOSURE_BLANK)


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


def _day_gap(date_str, prev_date):
    try:
        return max((date_cls.fromisoformat(date_str) - date_cls.fromisoformat(prev_date)).days, 1)
    except (TypeError, ValueError):
        return 1


def fold(prev_rows, stubs, parsed_rows, deal_events, date_str, vendor='591', closed_rows=None):
    '''回傳今日 snapshot 列（list of dict，依 vendor_house_id 排序）。
    closed_rows：{hid: 近幾天 snapshot 的最後一列}，只對「今日有 deals 事件但昨日不在 snapshot」
    的戶生效（見模組說明）。'''
    prev = {r['vendor_house_id']: r for r in prev_rows}
    stub_by = _latest(stubs, 'seen_at')
    parsed_by = _latest(parsed_rows, 'crawled_at')
    deal_by = _latest(deal_events, 'seen_at')
    closed_rows = closed_rows or {}

    out = []
    for hid in sorted(set(prev) | set(stub_by) | set(parsed_by) | set(deal_by)):
        yesterday = prev.pop(hid, None)   # 每戶只看一次：處理完即釋放昨日列（記憶體）
        gap = 1
        if yesterday is None and hid in deal_by and hid in closed_rows:
            yesterday = closed_rows[hid]
            gap = _day_gap(date_str, yesterday.get('date'))
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

        if parsed is not None and is_closure_row(parsed):
            # 404：只改狀態、不清值（DEAL sticky）
            if not (yesterday is not None and yesterday['deal_status'] == DEAL):
                row['deal_status'] = NOT_FOUND
            if stub is not None:
                for name in _LIST_FIELDS:
                    if stub.get(name) is not None:
                        row[name] = stub[name]
                row['source'] = 'list'
        elif parsed is not None:
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
            row['days_absent'] = (yesterday.get('days_absent') or 0) + gap

        deals.apply_deal(row, deal)   # vendor 事件永遠勝（#229）；inferred／n_day_deal 推導見 deals.py
        out.append(row)
    return out
