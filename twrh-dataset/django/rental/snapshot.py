'''snapshot 摺疊（Phase 4c；architecture-roadmap〈snapshot 即摺疊狀態〉）。

    today = fold(yesterday_snapshot, today_stubs, today_parsed, today_deal_events, date)

每日每戶一列，欄位＝parsed 全欄＋carry 欄（contracts.SNAPSHOT_FIELDS）。一階遞迴：
新環境冷啟只需昨日一份 snapshot。取代 synthts（合成被 skip 物件的當日列）與
House（現值＝最新 snapshot）。

規則（與現制 pipeline／synthts／syncstateful 語意逐條對齊）：
- 在 list：last_fingerprint＝最後一次 stub 指紋
- 今日有 detail（parsed）：整列覆蓋，source='detail'，last_detail_at＝crawled_at，
  fingerprint_at_last_detail＝last_fingerprint（今日在 list 就是今日的，否則是最後已知的）。
  **parsed 列的 None 不蓋既有值**（2026-09-19 拍板）：detail 從不帶 rough_address／
  vendor_house_url（list 給的），parser 這次沒抽到的 has_parking／管理費／房廳數也一樣——
  S3c dry-run 對 archive House 量到 rough_address 12,787 戶、vendor_house_url 4,533 戶被蓋成
  NULL，DB pipeline 十年來是留舊值。狀態欄（deal_status／deal_time／n_day_deal）與 crawled_at
  ／parser_version 例外，照舊由 detail 決定
- list 改價：per_ping_price 跟著重算（2026-09-19 拍板），公式同 detail parser＝
  (月租＋管理費＋停車費)／坪數；坪數缺就留 list 給的值。**每個 list 日都重算**（best
  effort，2026-09-20 維護者確認）：新月租＋列上攜帶的上次 detail 管理費／停車費，
  沒抓過的費用當 0＝退回月租／坪數。DB pipeline 在 list 日寫的是 list 頁「月租／坪數」
  （不含費用）、下次 detail 又蓋回含費用，同一戶在兩公式間輪流——snapshot 一致含費用，
  exportcheck 把「每坪租金」列 IMPROVED（snapshot 為準）
- list 日的格局編碼（apt_feature_code＝陽台／衛浴／房／廳各兩碼）同樣重組：list 頁只給
  房／廳，list 解析器把陽台／衛浴填 0 組碼（stub 全是 0000 開頭），照抄會把上次 detail
  的陽台／衛浴蓋掉——2026-09-19 snapshot 裡 30,808 戶 list 來源的整層住家全是 0000 開頭、
  其中 29,917 戶同一列的 n_balcony／n_bath_room 卻 > 0（欄與碼不一致）。改為以列上攜帶的
  n_balcony／n_bath_room＋list 的房／廳重組（2026-09-20）；list 沒給房／廳就不動
- 今日 detail 是 404／拒解析（parsed 列只帶 deal_status=NOT_FOUND、其餘 NULL）：只當
  狀態訊號——deal_status 改 NOT_FOUND（DEAL sticky 照舊），租金／座標等沿用最後已知值，
  source／last_detail_at 不動（DB 的 detail_crawled_at 也不因 404 更新）。關閉當天那列
  保留最後已知狀態，與 synthts 補齊關閉／成交列同形（2026-09-12 拍板）
- 只在 list：list 給的欄位（價格／格局…）覆蓋、其餘沿用昨日，source='list'；
  **昨日是關閉／成交而今日又出現在 list（且無關閉訊號）→ 回 OPENED、清掉
  deal_time／n_day_deal／deal_source**（2026-09-17 拍板）。重新掛上列表是在架的
  正面觀測，比昨日的關閉狀態新
- 都沒有：整列沿用昨日，source='carry'，days_absent+1
- 在 list：last_seen_at＝最後 seen_at、days_absent=0；first_seen_at 只在首見時設
- DEAL sticky 只擋「detail 404 回報 NOT_FOUND」這一條路（Issue #9），**不擋
  「它又出現在列表上」**——後者是正面觀測，見上一條；deals 事件（vendor 給
  deal_time／n_day_deal）永遠勝，deal_source='deals'；detail 回 NOT_FOUND 且
  昨日非 DEAL → NOT_FOUND（推導型成交留給下游，deal_source 不設）
- 已關閉（NOT_FOUND／DEAL）且今日無任何訊號的戶：不再攜帶（snapshot 只含
  當日仍有意義的列＝OPENED 或今日有事件），與現制 HouseTS「open 每日一列」一致
- 昨日 snapshot 沒有、今日又有訊號的戶（關閉多日後才進 591 成交列表；關閉後掉出、
  多日後又回列）：呼叫端可把「這戶最後已知的一列」用 closed_rows 傳進來當昨日列——
  來源是 S3c 總表 latest(昨日)（2026-09-19 起），沒有總表時退回掃近幾天 snapshot——
  成交列／回列才帶得出租金／座標等最後已知值（沒給就是只帶今日訊號的空白列＝
  snapshotcheck 的 deal_only_rows；回列戶整列空白是 S3c dry-run 挖出的第二個缺陷）。
  days_absent 依兩列日期差遞推。
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
# detail 列即使是 None 也照寫的欄：狀態與時間戳由 detail 決定；其餘 None＝「這次沒看到」不蓋舊值
_DETAIL_ALWAYS = ('deal_status', 'deal_time', 'n_day_deal', 'crawled_at', 'parser_version')


def _recompute_per_ping(row):
    '''list 改價後每坪租金跟著動（2026-09-19 拍板）；公式同 detail parser：
    (月租＋管理費＋停車費)／坪數。坪數缺就不動（留 list 自己算的或既有值）。'''
    price, ping = row.get('monthly_price'), row.get('floor_ping')
    if price is None or not ping:
        return
    row['per_ping_price'] = (price + (row.get('monthly_management_fee') or 0)
                             + (row.get('monthly_parking_fee') or 0)) / ping


def _recompute_apt_code(row):
    '''list 日重組格局編碼：陽台／衛浴取列上攜帶的（上次 detail），房／廳取 list 剛給的。
    list 沒給房／廳（套房等）就不動。'''
    bed, living = row.get('n_bed_room'), row.get('n_living_room')
    if bed is None or living is None:
        return
    row['apt_feature_code'] = '{:02d}{:02d}{:02d}{:02d}'.format(
        row.get('n_balcony') or 0, row.get('n_bath_room') or 0, bed, living)


def _apply_list_fields(row, stub):
    '''list 給的欄覆蓋（None＝這次沒看到，不蓋），再重算兩個推導欄。'''
    for name in _LIST_FIELDS:
        if stub.get(name) is not None:
            row[name] = stub[name]
    if stub.get('monthly_price') is not None:
        _recompute_per_ping(row)
    if stub.get('apt_feature_code') is not None:
        _recompute_apt_code(row)


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
    closed_rows：{hid: 這戶最後已知的一列}（S3c 總表或近幾天 snapshot），對「今日有任何訊號
    （stub／parsed／deals）但昨日不在 snapshot」的戶當昨日列用（見模組說明）。'''
    prev = {r['vendor_house_id']: r for r in prev_rows}
    stub_by = _latest(stubs, 'seen_at')
    parsed_by = _latest(parsed_rows, 'crawled_at')
    deal_by = _latest(deal_events, 'seen_at')
    closed_rows = closed_rows or {}

    out = []
    for hid in sorted(set(prev) | set(stub_by) | set(parsed_by) | set(deal_by)):
        yesterday = prev.pop(hid, None)   # 每戶只看一次：處理完即釋放昨日列（記憶體）
        gap = 1
        stub = stub_by.get(hid)
        parsed = parsed_by.get(hid)
        deal = deal_by.get(hid)
        touched = stub is not None or parsed is not None or deal is not None
        if yesterday is None and touched and hid in closed_rows:
            yesterday = closed_rows[hid]
            gap = _day_gap(date_str, yesterday.get('date'))
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
                # 404 勝、但 list 的其他資料照帶（2026-09-19 維護者確認）
                _apply_list_fields(row, stub)
                row['source'] = 'list'
        elif parsed is not None:
            if stub is not None:
                # 同日在 list：list 給的欄（rough_address 等 detail 從不帶的）先落，detail 再覆蓋
                _apply_list_fields(row, stub)
            for name in _PARSED_COPY:
                if name not in parsed:
                    continue
                if parsed[name] is None and name not in _DETAIL_ALWAYS:
                    continue   # None＝這次沒看到，不蓋既有值（2026-09-19）
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
            _apply_list_fields(row, stub)
            row['source'] = 'list'
            # 重新出現在 list 且今日無關閉／成交訊號＝在架的正面證據，狀態要回
            # OPENED（2026-09-17 維護者拍板）。此前沒有任何路徑會把 deal_status
            # 改回來——LIST_STUB_FIELDS 不含 deal_status，這個分支只複製
            # _LIST_FIELDS，於是 snapshot 裡一旦標成關閉就回不來，天天出現在
            # 列表上也一樣（S1 dry-run 挖出來：snapshot deal_status=1 而 House=0、
            # 且昨日今日都在列）。影響的不只 seed——S3a 之後 export 讀 snapshot，
            # 公開資料會把還在市場上的物件標成已下架。
            # DEAL 也不例外：sticky 只擋「detail 404 回報 NOT_FOUND」那條路
            #（Issue #9），不擋「它又出現在列表上」這種正面觀測。
            if row['deal_status'] != OPENED:
                row['deal_status'] = OPENED
                row['deal_time'] = None
                row['n_day_deal'] = None
                row['deal_source'] = None

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
