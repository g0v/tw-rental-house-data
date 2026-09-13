'''DEAL 推導（Phase 4d 推導側；architecture-roadmap 開放問題 #10 拍板）。

2026 改版後 detail 頁在成交後回 404，DEAL 的**唯一原生來源**是 deals stage（deal591 走
591「已成交」列表）產的事件；時序推導（舊 syncstateful 的 O O D D N N 型態）已無輸入。
snapshot 世界裡的成交狀態因此只有兩種血統：

- deal_source='deals'：vendor 給 deal_time／n_day_deal（永遠勝、sticky）
- deal_source='inferred'：昨日已是 DEAL 但沒有來源標記（bootstrap 之前的 DB 舊列）——
  只保留狀態，n_day_deal 缺的時候由 deal_time − first_seen_at 推

n_day_deal 的推導型定義＝成交日與首見日的日曆日差（台北時區）。591 自己的「N天成交」
多半等於此值或 +1（#6 調查：兩套量法差集中在 0～+1 天）；vendor 值存在時一律用 vendor 的。

不 import Django；fold（rental/snapshot.py）呼叫 apply_deal。
'''
from datetime import datetime, timedelta, timezone

DEAL = 2   # rental.enums.DealStatusType.DEAL（只增不改）
DEAL_FIELDS = ('deal_status', 'deal_time', 'n_day_deal', 'deal_source')
TAIPEI = timezone(timedelta(hours=8))


def _local_date(value):
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        value = value.astimezone(TAIPEI)
    return value.date()


def n_day_deal_inferred(deal_time, first_seen_at):
    '''推導型 n_day_deal＝deal_time 與 first_seen_at 的日曆日差（≥0）；任一缺或非 datetime → None。'''
    a, b = _local_date(deal_time), _local_date(first_seen_at)
    if a is None or b is None:
        return None
    return max((a - b).days, 0)


def apply_deal(row, event):
    '''fold 的成交段（就地修改並回傳 row）：
    - 今日有 deals 事件：DEAL、vendor 的 deal_time／n_day_deal、deal_source='deals'
    - 否則 row 已是 DEAL（昨日 sticky 帶來）而無來源標記 → 'inferred'
    - DEAL 而 n_day_deal 缺（inferred 列、或 vendor 沒給）→ 由 deal_time − first_seen_at 推'''
    if event is not None:
        row['deal_status'] = DEAL
        row['deal_time'] = event.get('deal_time')
        row['n_day_deal'] = event.get('n_day_deal')
        row['deal_source'] = 'deals'
    elif row.get('deal_status') == DEAL and row.get('deal_source') is None:
        row['deal_source'] = 'inferred'
    if row.get('deal_status') == DEAL and row.get('n_day_deal') is None:
        row['n_day_deal'] = n_day_deal_inferred(row.get('deal_time'), row.get('first_seen_at'))
    return row


def deal_state(row):
    '''一戶的成交狀態四欄（House 現值＝最新 snapshot 的這四欄；syncstateful 退役後的讀法）。'''
    return {name: row.get(name) for name in DEAL_FIELDS}
