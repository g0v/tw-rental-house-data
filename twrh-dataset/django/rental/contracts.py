'''normalized 契約（Phase 4：檔案分區的 schema 之家）。

架構計畫〈schema 演進紀律〉：raw 無 schema、vendor parse 中間產物
（detail_dict）不再持久化，落地的是我們控制的 normalized 契約。兩張表：

- **list stub**（4a）：list 頁的一次觀測，一筆＝一戶一輪；`fingerprint`
  存雜湊不存 title 原文（raw 365 天過期後 stub 仍可永存）。
- **parsed**（4b）：detail 成功解析後的 normalized 列（＝GenericHouseItem
  欄位），一筆＝一戶一次 detail；同日多輪各自一個 parquet。

契約只增不改：新欄位 nullable append；改語意＝新欄位＋棄用註記；讀取端
`union_by_name` 掃跨日分區。這裡不 import Django——manage.py 行程、
scrapy 行程與離線工具（rerun_from_raws）三處共用，且 4f 去 Django 時
它就是 models.py 的接替者。pyarrow 只在 parquet 寫入時才 import。
'''
import enum
import hashlib
import json
from datetime import date, datetime

LIST_STUB_VERSION = 1
PARSED_VERSION = 1

# --- 型別代號（與 pyarrow 解耦，pack 時再映射） -------------------------------
STR, I32, I64, F64, BOOL, TS, JSON = 'str', 'i32', 'i64', 'f64', 'bool', 'ts', 'json'

# list stub：normalized 子集（list 頁本來就沒有 detail 欄位）；
# 不含 title／imgs／contact 姓名等原文，指紋另存雜湊
LIST_STUB_FIELDS = [
    ('vendor', STR),            # vendor 短名（'591'），對齊目錄／S3 key
    ('vendor_house_id', STR),
    ('date', STR),              # 日期 bucket（TWRH_TARGET_DATE）
    ('run', STR),               # flow run id：run／sweep-HHMM／manual
    ('seen_at', TS),            # 真實觀測時刻（記錄型時間戳，與 bucket 分開）
    ('fingerprint', STR),       # sha1(price, title)[:16]
    ('top_region', I32),
    ('sub_region', I32),
    ('property_type', I32),
    ('monthly_price', I64),
    ('min_monthly_price', I64),
    ('per_ping_price', F64),
    ('floor_ping', F64),
    ('floor', I32),
    ('total_floor', I32),
    ('is_rooftop', BOOL),
    ('dist_to_highest_floor', I32),
    ('n_bed_room', I32),
    ('n_living_room', I32),
    ('n_bath_room', I32),
    ('apt_feature_code', STR),
    ('rough_address', STR),
    ('contact', I32),
    ('can_cook', BOOL),
    ('allow_pet', BOOL),
    ('stub_version', I32),
]
LIST_FINGERPRINT_KEYS = ('price', 'title')

# parsed：BaseHouse 全欄（vendor FK→短名字串、Point→lat/lng、JSON→字串、
# author 電話→雜湊）＋來源欄
PARSED_FIELDS = [
    ('vendor', STR),
    ('vendor_house_id', STR),
    ('date', STR),
    ('run', STR),
    ('crawled_at', TS),
    ('parser_version', STR),    # scrapy-tw-rental-house 版本
    ('top_region', I32),
    ('sub_region', I32),
    ('deal_time', TS),
    ('deal_status', I32),
    ('n_day_deal', I32),
    ('vendor_house_url', STR),
    ('monthly_price', I64),
    ('min_monthly_price', I64),
    ('deposit_type', I32),
    ('n_month_deposit', F64),
    ('deposit', I64),
    ('is_require_management_fee', BOOL),
    ('monthly_management_fee', I64),
    ('has_parking', BOOL),
    ('is_require_parking_fee', BOOL),
    ('monthly_parking_fee', I64),
    ('per_ping_price', F64),
    ('building_type', I32),
    ('property_type', I32),
    ('is_rooftop', BOOL),
    ('floor', I32),
    ('total_floor', I32),
    ('dist_to_highest_floor', I32),
    ('floor_ping', F64),
    ('n_living_room', I32),
    ('n_bed_room', I32),
    ('n_bath_room', I32),
    ('n_balcony', I32),
    ('apt_feature_code', STR),
    ('rough_address', STR),
    ('rough_lat', F64),
    ('rough_lng', F64),
    ('additional_fee', JSON),
    ('living_functions', JSON),
    ('transportation', JSON),
    ('has_tenant_restriction', BOOL),
    ('has_gender_restriction', BOOL),
    ('gender_restriction', I32),
    ('can_cook', BOOL),
    ('allow_pet', BOOL),
    ('has_perperty_registration', BOOL),
    ('facilities', JSON),
    ('contact', I32),
    ('author_key', STR),        # sha1(author 識別字串)[:16]，仲介行為分析用
    ('agent_org', STR),
    ('imgs', JSON),
    ('parsed_version', I32),
]

_SCALAR_FROM_ITEM = {name for name, _ in PARSED_FIELDS} - {
    'vendor', 'vendor_house_id', 'date', 'run', 'crawled_at',
    'parser_version', 'rough_lat', 'rough_lng', 'author_key', 'parsed_version'}


def short_hash(*parts):
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]


def list_fingerprint(raw_dict):
    '''list 指紋：只看 price／title（update_time 是相對字串會天天漂）。
    與 pipeline 舊制的 (price, title) 比對同義，只是改存雜湊。'''
    return short_hash(*[raw_dict.get(key) for key in LIST_FINGERPRINT_KEYS])


def _plain(value):
    '''item 值 → 可 JSON 化的 normalized 值。'''
    if isinstance(value, enum.Enum):
        return int(value) if isinstance(value, int) else value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def list_stub(vendor_short, house_id, date_str, run, seen_at, fingerprint,
              generic_fields):
    row = {
        'vendor': vendor_short,
        'vendor_house_id': str(house_id),
        'date': date_str,
        'run': run,
        'seen_at': seen_at.isoformat(),
        'fingerprint': fingerprint,
        'stub_version': LIST_STUB_VERSION,
    }
    for name, _ in LIST_STUB_FIELDS:
        if name in row:
            continue
        row[name] = _plain(generic_fields.get(name))
    return row


def parsed_row(vendor_short, house_id, date_str, run, crawled_at,
               parser_version, generic_fields):
    row = {
        'vendor': vendor_short,
        'vendor_house_id': str(house_id),
        'date': date_str,
        'run': run,
        'crawled_at': crawled_at.isoformat(),
        'parser_version': parser_version,
        'parsed_version': PARSED_VERSION,
        'rough_lat': None,
        'rough_lng': None,
        'author_key': None,
    }
    coord = generic_fields.get('rough_coordinate')
    if coord is not None:
        # item 是 (lat, lng) tuple。pipeline 直接 Point(tuple) 入庫，所以本專案 DB 的
        # PointField 是 x=lat、y=lng（與 GIS 慣例 x=lng 相反；2026-09-09 parsedcheck
        # 實測確認）——讀 DB Point 時照這個約定拆，不要「修正」它
        if hasattr(coord, 'y') and hasattr(coord, 'x'):
            row['rough_lat'], row['rough_lng'] = float(coord.x), float(coord.y)
        else:
            row['rough_lat'], row['rough_lng'] = float(coord[0]), float(coord[1])
    author = generic_fields.get('author')
    if author:
        row['author_key'] = short_hash(str(author))
    for name in _SCALAR_FROM_ITEM:
        row[name] = _plain(generic_fields.get(name))
    return row


# --- pyarrow 映射（只在 pack 時用） ---------------------------------------------

def arrow_schema(fields):
    import pyarrow as pa
    mapping = {
        STR: pa.string(), I32: pa.int32(), I64: pa.int64(), F64: pa.float64(),
        BOOL: pa.bool_(), TS: pa.timestamp('us', tz='UTC'), JSON: pa.string(),
    }
    return pa.schema([pa.field(name, mapping[kind], nullable=True)
                      for name, kind in fields])


def _parse_ts(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def coerce_row(row, fields):
    '''jsonl 列 → 符合 schema 的 python dict（缺欄補 None、型別收斂）。'''
    out = {}
    for name, kind in fields:
        value = row.get(name)
        if value is None:
            out[name] = None
        elif kind == TS:
            out[name] = _parse_ts(value)
        elif kind in (I32, I64):
            out[name] = int(value)
        elif kind == F64:
            out[name] = float(value)
        elif kind == BOOL:
            out[name] = bool(value)
        elif kind == JSON:
            out[name] = value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False, sort_keys=True)
        else:
            out[name] = str(value)
    return out
