'''S3a：export 的 snapshot 讀取端（只改讀取來源，不動輸出欄位定義）。

來源＝一天一檔的 `artifacts/snapshot/<vendor>/<date>.parquet`（4c fold 產物）。
區間 export 取窗內每日檔，逐戶取「最後一天出現的那一列」——carry 列帶的就是該戶
最後已知值，與 DB 路徑讀 `House` 現況同義（export 排在當日爬取之前跑）。

DB 路徑的篩選對映（2026-09-18 首次 exportcheck 校準；細節見 `_in_window`）：
  - 曾經 detail 成功過＝窗內任一列有 `additional_fee`（DB 是 House 現值 isnull=False）
  - 首次發現 <= 窗尾（DB 是 created__lte）
  - **窗內有列**即可，不另外要求 last_seen/last_detail >= 窗首（DB 的 crawled_at 幾乎
    天天被 list／synthts／deals 刷新，照字面比會少 15,110 戶）

**三欄對映**（2026-09-17 維護者拍板，差異寫進 schema 1.0 §3.5 與 issue #238）：
  物件首次發現時間 ← `first_seen_at`（DB 是 House.created＝列插入時間）
  物件最後更新時間 ← max(`last_seen_at`, `last_detail_at`, `crawled_at`)（DB 是 House.updated）
  刊登者編碼       ← `author_key`＝sha1(Author.truth)[:16]（DB 是 Author.uuid；
                     UUID↔author_key 的世代對照由 S2b 的 rental_author 保存）

**列序**改為物件編號遞減（DB 路徑是 `House.id` 遞減，parquet 沒有也不該有 DB 主鍵）。
比對門檻因此是「排序正規化後逐 byte 一致」（2026-09-17 拍板）。

記憶體：不把整窗攤成 python dict（月窗十幾萬戶 × 60 欄 ≈ 1 GB，publisher 只有 4 GB）。
做法＝先掃各日檔的 id 欄建指標（house_id → 哪一天、第幾列），再逐日 take() 需要的列
留成 arrow table，最後照排序鍵一列一列materialize。
'''
import json
import os
from datetime import datetime, timedelta

import pyarrow.parquet as pq

# JSON 欄在 parquet 裡是字串（contracts 約定）；DB 路徑用 KeyTextTransform 取出來是
# 文字（true／false／數字字串），to_human 兩種都吃，所以這裡直接給 python 值。
_JSON_COLUMNS = ('additional_fee', 'living_functions', 'transportation', 'facilities')

# 591 2026 模板把桌子、椅子併成「桌椅」：兩欄照舊語意出（0.3 修正，與 DB 路徑的
# Coalesce 同義）
_FACILITY_FALLBACK = {'桌子': '桌椅', '椅子': '桌椅'}


def snapshot_dir(vendor='591'):
    base = os.environ.get('TWRH_ARTIFACT_DIR') or 'artifacts'
    return os.path.join(base, 'snapshot', vendor)


class _Point:
    '''只為了餵 RawExport 的 `fn=lambda p: p.x`——DB 的 PointField 是 x=lat／y=lng
    （twrh-db-point-axis-quirk，讀時不修正），parquet 存的是 rough_lat／rough_lng。'''

    __slots__ = ('x', 'y')

    def __init__(self, lat, lng):
        self.x = lat
        self.y = lng


class SnapshotWindow:
    '''窗內逐戶最後一列，支援 len()／切片，可直接餵 django Paginator。'''

    def __init__(self, from_date, to_date, vendor='591', vendor_id=None,
                 columns=None, sort_desc=True):
        self.vendor = vendor
        self.vendor_id = vendor_id
        self.from_date = from_date
        self.to_date = to_date
        self._tables = {}        # date_str -> arrow table（只含需要的列）
        self._index = []         # [(house_id, date_str, local_idx), ...] 排序後
        self._columns = columns
        self._build(sort_desc)

    # ---- 建指標 ----------------------------------------------------------

    def _dates(self):
        # to_date 由 export 傳進來時已是「窗尾＋1 天 00:00」（排他），日檔取到窗尾那天
        day = self.from_date.date() if hasattr(self.from_date, 'date') else self.from_date
        end = self.to_date.date() if hasattr(self.to_date, 'date') else self.to_date
        out = []
        while day < end:
            path = os.path.join(snapshot_dir(self.vendor), day.isoformat() + '.parquet')
            if os.path.exists(path):
                out.append((day.isoformat(), path))
            day += timedelta(days=1)
        return out

    def _build(self, sort_desc):
        days = self._dates()
        if not days:
            raise FileNotFoundError(
                'no snapshot parquet under {} for {}..{}'.format(
                    snapshot_dir(self.vendor), self.from_date, self.to_date))
        self.days = [d for d, _ in days]

        # pass 1：逐戶取最後一天那列；同時記「窗內任一列有 additional_fee」＝曾經
        # detail 成功過（DB 的 House.additional_fee 是最後已知非空值，見 _in_window）
        latest = {}
        self._ever_fee = set()
        for date_str, path in days:
            t = pq.read_table(path, columns=['vendor_house_id', 'additional_fee'])
            ids = t.column('vendor_house_id').to_pylist()
            fees = t.column('additional_fee').to_pylist()
            for i, hid in enumerate(ids):
                latest[hid] = (date_str, i)
                if fees[i] is not None:
                    self._ever_fee.add(hid)

        # pass 2：逐日 take 需要的列，篩掉不該出的戶
        by_day = {}
        for hid, (date_str, i) in latest.items():
            by_day.setdefault(date_str, []).append((hid, i))
        kept = []
        for date_str, path in days:
            rows = by_day.get(date_str)
            if not rows:
                continue
            table = pq.read_table(path, columns=self._columns)
            idx = [i for _hid, i in rows]
            table = table.take(idx)
            keep_local = []
            for local, (hid, _i) in enumerate(rows):
                if self._in_window(table, local, hid):
                    keep_local.append(local)
                    kept.append((hid, date_str, len(keep_local) - 1))
            self._tables[date_str] = table.take(keep_local)
        self._index = sorted(kept, key=lambda r: r[0], reverse=sort_desc)

    def _in_window(self, table, local, hid):
        '''DB 路徑的三道篩對映（2026-09-18 首次 exportcheck 校準過）：

        - `additional_fee__isnull=False`：DB 看的是 House 現值＝**曾經 detail 成功過**，
          不是「最後一列有值」。窗內任一列有就算（`self._ever_fee`）——snapshot 有
          ~1,300 列的值比 DB 稀薄（2026-09-16 synthts 回補之前摺進去的稀疏列），
          只看最後一列會把這些戶整戶漏掉。
        - `created__lte=to_date`：first_seen_at <= 窗尾。
        - ~~`crawled_at__gte=from_date`~~ **不再對映成 max(last_seen_at, last_detail_at)**：
          DB 的 `crawled_at` 是「最後一次有任何 item 寫進來」，而 list／synthts／deals
          幾乎天天碰到每一戶，所以那道篩在 DB 端幾乎不篩掉東西；snapshot 端照字面
          比對會少 15,110 戶（首次 exportcheck 實測）。**窗內有列＝我們那幾天手上有它**
          就是等價條件——fold 只在「已關閉且當日無訊號」時才不再攜帶。
        '''
        def val(name):
            col = table.column(name)
            return col[local].as_py() if name in table.column_names else None

        if hid not in self._ever_fee:
            return False
        first_seen = val('first_seen_at')
        if first_seen is not None and first_seen > self.to_date:
            return False
        return True

    # ---- 取列 ------------------------------------------------------------

    def __len__(self):
        return len(self._index)

    def __getitem__(self, item):
        if isinstance(item, slice):
            return [self._row(i) for i in range(*item.indices(len(self._index)))]
        return self._row(item)

    def _row(self, i):
        hid, date_str, local = self._index[i]
        table = self._tables[date_str]
        raw = {name: table.column(name)[local].as_py()
               for name in table.column_names}
        return self._to_export_row(raw)

    def _to_export_row(self, raw):
        '''parquet 一列 → export 的 dict（key＝Field.source）。'''
        row = dict(raw)
        row['vendor'] = self.vendor_id
        row['house_url'] = 'https://rent.591.com.tw/{}'.format(raw['vendor_house_id'])
        row['created'] = raw.get('first_seen_at')
        # crawled_at fallback（2026-09-17 維護者拍板）：#11 回填的 9/1–9/10 沒有
        # last_seen_at／last_detail_at，而那些戶的「窗內最後一列」就落在那幾天——
        # 只取前兩者，九月窗有 31.5%（47,698／151,423）會變 '-'。crawled_at＝該列那天
        # 實際爬到的時間，語意上正是「我們最後一次更新這戶」，而 DB 的 House.updated
        # 對已關閉的戶也就是最後一次寫入。實測這 47,698 列 100% 都有它。
        row['updated'] = max(
            [v for v in (raw.get('last_seen_at'), raw.get('last_detail_at'),
                         raw.get('crawled_at')) if v is not None], default=None)
        row['author'] = raw.get('author_key')
        lat, lng = raw.get('rough_lat'), raw.get('rough_lng')
        point = _Point(lat, lng) if lat is not None else None
        # 兩欄的 Field 都以 rough_coordinate 為 column 但 en 各自改名，source 因此是
        # rough_coordinate_x／_y（DB 路徑用 extra_fields 起同名 alias）
        row['rough_coordinate'] = point
        row['rough_coordinate_x'] = point
        row['rough_coordinate_y'] = point

        for column in _JSON_COLUMNS:
            parsed = json.loads(raw[column]) if raw.get(column) else {}
            row[column] = parsed
        return row


def decorate_json_keys(row, headers):
    '''把 JSON 欄展平成 `<column>_<key>`（DB 路徑由 KeyTextTransform 產出同名 key）。'''
    for header in headers:
        if not header.field:
            continue
        parsed = row.get(header.column)
        if not isinstance(parsed, dict):
            row[header.source] = None
            continue
        val = parsed.get(header.field)
        if val is None and header.field in _FACILITY_FALLBACK:
            val = parsed.get(_FACILITY_FALLBACK[header.field])
        row[header.source] = val
    return row


def parse_target_date(value):
    return datetime.strptime(value, '%Y-%m-%d').date()
