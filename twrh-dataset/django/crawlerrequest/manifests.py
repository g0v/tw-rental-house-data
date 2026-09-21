'''manifest 產生器（architecture-roadmap 1-2：觀測層單一機制）。

每個 stage 一份 `manifests/<date>/<stage>.json`——進出筆數、queue 終結
統計、逐欄填充率、分佈統計、版本。品質門檻＝`quality/assertions.yaml`
對 manifest 的斷言（qualitycheck）；日檢、月報、漂移偵測是同一機制的
不同時間窗。

manifest 是「對當日資料的純函數」：同一天重算結果相同，也因此可從 DB
回補歷史（1-3 的 9 月 backfill）——queue 終結統計在舊制（刪列＝完成）
下已丟，回補時缺項標 source=backfill、對應斷言由引擎降 advisory。

**S3b（house 三表停寫）起來源改為分區檔**（`rental.switches.house_db()` 為假時）：四份
manifest 由當日 snapshot／list stub／parsed 分區算出，欄位與 DB 版同名同義，`source` 標
`partitions`。定義上的對映與已知差：
  當日列（HouseTS 該日 bucket）      ← 當日 snapshot 的列
  在今日 list（list_crawled_at 有值）  ← 今日 stub 出現過的戶
  確認開放（非合成列）               ← snapshot `source == 'detail'` 的 OPENED 列。DB 版的「非合成」
                                       還含「只在 list、從未 detail 的新戶」（synthts 沒東西可補＝untouched，
                                       每日約 850 戶）；那批必在 list，拿掉後 capture.ratio 低約 0.001
  合成列數 n_synthesized              ← snapshot `source != 'detail'`（同上，多約 850）
  fill_rate 樣本                      ← **今日 parsed 分區**的 OPENED 列（每戶取最後一列）。刻意不用
                                       snapshot：fold 的「None 不蓋值」會拿舊值補洞，正好遮住 parser
                                       靜默失效，而 fill_rate 就是為了抓它。detail 從不帶的
                                       rough_address 改看同戶的 snapshot 列（list 給的）
  dist 樣本                           ← 當日 snapshot 的 OPENED 列
  n_new_item（House.created 在當日）  ← snapshot `first_seen_at` 落在當日（台北日界）

stage 對應現制（3-2 flow 收斂前的過渡分界）：
  list     — list 爬取＋L-B 捕獲哨兵
  detail   — detail 爬取＋解析（fill_rate／dist 都量在這）
  deals    — 「已成交」列表產出的成交事件（#229）：當日 TS 的 DEAL 列
  snapshot — syncstateful／synthts 之後的當日 TS 總覽
'''
import json
import os
from datetime import datetime, timedelta
from importlib.metadata import version, PackageNotFoundError

from django.db.models import Count
from django.utils import timezone

from scrapy_twrh.cli.runner import invariants
from scrapy_twrh.extensions.fill_rate import is_filled

try:
    PARSER_VERSION = version('scrapy-tw-rental-house')
except PackageNotFoundError:
    PARSER_VERSION = 'unknown'

from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestType, RequestStatus
from rental import enums
from rental.enums import DealStatusType
from rental.models import House, HouseTS
from rental.switches import house_db

# 檔案層（路徑／讀寫／dot-path 取值）住在 manifest_files.py——純函數、
# 無 Django 相依，離線斷言（tools/quality_offline.py）直接 import 那邊；
# 這裡 re-export 維持既有 import 路徑
from crawlerrequest.manifest_files import (  # noqa: F401
    SCHEMA_VERSION, DEFAULT_DIR, manifest_dir, manifest_path,
    write_manifest, load_manifest, get_metric)

# fill_rate 追的欄位：GenericHouseItem 與 HouseTS 的交集（DB 層量法，
# 1-2 起為唯一基準；survey 層 FillRateMonitor 於切換日退役）
FILL_RATE_FIELDS = [
    'top_region', 'sub_region', 'monthly_price', 'deposit_type',
    'n_month_deposit', 'deposit', 'is_require_management_fee',
    'monthly_management_fee', 'has_parking', 'is_require_parking_fee',
    'monthly_parking_fee', 'per_ping_price', 'building_type',
    'property_type', 'is_rooftop', 'floor', 'total_floor',
    'dist_to_highest_floor', 'floor_ping', 'n_living_room', 'n_bed_room',
    'n_bath_room', 'n_balcony', 'apt_feature_code', 'rough_address',
    'rough_coordinate', 'additional_fee', 'living_functions',
    'transportation', 'has_tenant_restriction', 'has_gender_restriction',
    'gender_restriction', 'can_cook', 'allow_pet', 'facilities',
    'contact', 'agent_org', 'imgs',
]


def _ts_of(date_obj):
    return {
        'year': date_obj.year, 'month': date_obj.month,
        'day': date_obj.day, 'hour': 0,
    }


def _queue_stats(ts, request_type, source):
    '''queue 終結統計（1-1 狀態機）。backfill 模式下舊制已刪列，統計不可信
    ——整節缺席，斷言引擎對缺 metric 的檢查自動降 advisory。
    S4a（TWRH_QUEUE_SOURCE=file）改讀檔案 queue（各 vendor 加總），同欄位。'''
    if source == 'backfill':
        return None
    if os.environ.get('TWRH_QUEUE_SOURCE', 'db') == 'file':
        return _queue_stats_file(ts, request_type)
    by_status = dict(
        RequestTS.objects.filter(**ts, request_type=request_type)
        .values_list('status').annotate(n=Count('id')))
    seeds = sum(by_status.values())
    done = by_status.get(int(RequestStatus.DONE), 0)
    dead = by_status.get(int(RequestStatus.DEAD), 0)
    residue = seeds - done - dead
    errors = {
        row['error']: row['count']
        for row in RequestTS.objects.filter(**ts, request_type=request_type)
        .exclude(status=RequestStatus.DONE).exclude(error__isnull=True)
        .values('error').annotate(count=Count('id'))}
    return {
        'seeds': seeds,
        'done': done,
        'dead': dead,
        'residue': residue,
        'dead_ratio': round(dead / seeds, 4) if seeds else 0.0,
        'errors': errors,
    }


def _queue_stats_file(ts, request_type):
    from rental import filequeue
    from rental.models import Vendor
    from rental.raws import vendor_dirname
    date_str = '{year:04d}-{month:02d}-{day:02d}'.format(**ts)
    type_name = RequestType(request_type).name.lower()
    max_attempts = int(os.environ.get('TWRH_QUEUE_MAX_ATTEMPTS', 3))
    total = {'seeds': 0, 'done': 0, 'dead': 0, 'residue': 0}
    errors = {}
    for vendor in Vendor.objects.all():
        short = vendor_dirname(vendor.name)
        if type_name not in filequeue.type_names(short, date_str):
            continue
        r = filequeue.reconcile(short, date_str, type_name, max_attempts)
        for k in total:
            total[k] += r[k]
        for err, n in r['errors'].items():
            errors[err] = errors.get(err, 0) + n
    return {
        **total,
        'dead_ratio': round(total['dead'] / total['seeds'], 4) if total['seeds'] else 0.0,
        'errors': errors,
        'source': 'file',
    }


def _base(stage, date_obj, source):
    return {
        'schema': SCHEMA_VERSION,
        'stage': stage,
        'date': date_obj.isoformat(),
        'generated_at': timezone.localtime().isoformat(),
        'source': source,
        'parser_version': PARSER_VERSION,
    }


def _enum_or_none(enum_cls, value):
    if value is None:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return value


def _partition_block(stage, date_obj):
    '''並列輸出（4a–4d 雙寫期）：同一 stage 由分區檔算出的計數，與 DB 版並排放在
    manifest 的 `partitions` 節（每 vendor 一塊，key＝短名）。缺分區＝該 vendor 不出現；
    算失敗只留 error、不影響 DB 版（manifest stage 不能因分區檔紅）。切換階梯走完後
    DB 版退場、這裡升為唯一。'''
    from rental import artifacts
    from rental.models import Vendor
    from rental.raws import vendor_dirname
    bucket = os.environ.get('TWRH_RAW_BUCKET')
    date_str = date_obj.isoformat()
    out = {}
    for vendor in Vendor.objects.all():
        short = vendor_dirname(vendor.name)
        try:
            block = _PARTITION_COUNTERS[stage](short, date_str, bucket, artifacts)
        except Exception as err:  # noqa: BLE001
            block = {'error': '{}: {}'.format(type(err).__name__, err)}
        if block:
            out[short] = block
    return out


def _count_list(short, date_str, bucket, artifacts):
    houses, runs, n = set(), set(), 0
    for stub in artifacts.read_list_stubs(short, date_str, bucket):
        n += 1
        houses.add(stub['vendor_house_id'])
        runs.add(stub.get('run'))
    if not n:
        return None
    return {'n_stubs': n, 'n_houses': len(houses), 'runs': sorted(r for r in runs if r)}


def _count_parquet(tree, short, date_str, bucket, artifacts, columns):
    import pyarrow.parquet as pq
    tables = [pq.read_table(path, columns=columns)
              for path in artifacts.partition_files(tree, short, date_str, bucket)]
    return [row for table in tables for row in table.to_pylist()]


def _count_parsed(short, date_str, bucket, artifacts):
    rows = _count_parquet('parsed', short, date_str, bucket, artifacts, ['vendor_house_id', 'run'])
    if not rows:
        return None
    return {'n_rows': len(rows), 'n_houses': len({r['vendor_house_id'] for r in rows}),
            'runs': sorted({r['run'] for r in rows if r['run']})}


def _count_deals(short, date_str, bucket, artifacts):
    rows = _count_parquet('deals', short, date_str, bucket, artifacts,
                          ['vendor_house_id', 'deal_time', 'run'])
    if not rows:
        return None
    by_date = {}
    for r in rows:
        key = timezone.localtime(r['deal_time']).date().isoformat() if r['deal_time'] else 'unknown'
        by_date[key] = by_date.get(key, 0) + 1
    return {'n_events': len(rows), 'n_houses': len({r['vendor_house_id'] for r in rows}),
            'runs': sorted({r['run'] for r in rows if r['run']}),
            'by_deal_date': dict(sorted(by_date.items()))}


def _count_snapshot(short, date_str, bucket, artifacts):
    import pyarrow.parquet as pq
    path = artifacts._fetch_snapshot(short, date_str, bucket)
    if path is None:
        return None
    table = pq.read_table(path, columns=['deal_status', 'source', 'deal_source'])
    by_source, by_deal_source, by_status = {}, {}, {}
    for r in table.to_pylist():
        by_source[r['source']] = by_source.get(r['source'], 0) + 1
        by_status[r['deal_status']] = by_status.get(r['deal_status'], 0) + 1
        if r['deal_source']:
            by_deal_source[r['deal_source']] = by_deal_source.get(r['deal_source'], 0) + 1
    return {
        'n_total': table.num_rows,
        'n_opened': by_status.get(int(DealStatusType.OPENED), 0),
        'n_closed': by_status.get(int(DealStatusType.NOT_FOUND), 0),
        'n_dealt': by_status.get(int(DealStatusType.DEAL), 0),
        'by_source': dict(sorted(by_source.items())),
        'by_deal_source': dict(sorted(by_deal_source.items())),
    }


_PARTITION_COUNTERS = {
    'list': _count_list, 'detail': _count_parsed,
    'deals': _count_deals, 'snapshot': _count_snapshot,
}


def build_list_manifest(date_obj, source='live'):
    ts = _ts_of(date_obj)
    opened = HouseTS.objects.filter(**ts, deal_status=DealStatusType.OPENED)
    n_open = opened.count()
    n_in_list = opened.filter(list_crawled_at__isnull=False).count()
    # L-B 完整度哨兵（2026-09-05 重定義）：分母只取「detail 當日確認開放」
    # （非合成列）。合成列＝今天沒爬 detail、狀態未知，其中不在 list 的那批
    # 96% 是尚未確認的關閉（第一天缺席，隔天由 absent>=2d 種子 404 確認），
    # 算進分母會把每日下架量誤讀成漏抓（09-05 實測 0.92 vs 確認開放 1.00）。
    # 已知偏差：diff 模式下活著卻缺席的物件要缺席滿兩天才排 detail，同日
    # 漏抄要兩天後才反映；full 模式下兩者相同。
    confirmed = opened.exclude(is_synthesized=True)
    n_confirmed = confirmed.count()
    n_confirmed_in_list = confirmed.filter(list_crawled_at__isnull=False).count()
    # 待確認關閉存量：合成且不在 list——市場每日下架量的代理，只觀測不判紅
    n_pending_absent = opened.filter(
        is_synthesized=True, list_crawled_at__isnull=True).count()
    return {
        **_base('list', date_obj, source),
        'queue': _queue_stats(ts, RequestType.LIST, source),
        'counts': {
            'n_in_list': HouseTS.objects.filter(
                **ts, list_crawled_at__isnull=False).count(),
        },
        'capture': {
            'n_open': n_open,
            'n_open_in_list': n_in_list,
            'n_confirmed_open': n_confirmed,
            'n_confirmed_open_in_list': n_confirmed_in_list,
            'ratio': (round(n_confirmed_in_list / n_confirmed, 4)
                      if n_confirmed else None),
            # 舊定義留檔對照（分母含合成列）
            'ratio_all_open': round(n_in_list / n_open, 4) if n_open else None,
            'n_pending_absent': n_pending_absent,
        },
        'partitions': _partition_block('list', date_obj),
    }


def build_detail_manifest(date_obj, source='live'):
    ts = _ts_of(date_obj)
    day_rows = HouseTS.objects.filter(**ts)
    by_deal = dict(day_rows.values_list('deal_status').annotate(n=Count('id')))
    n_opened = by_deal.get(int(DealStatusType.OPENED), 0)
    n_closed = by_deal.get(int(DealStatusType.NOT_FOUND), 0)
    n_dealt = by_deal.get(int(DealStatusType.DEAL), 0)

    day_start = timezone.make_aware(
        datetime(date_obj.year, date_obj.month, date_obj.day))
    n_new = House.objects.filter(
        created__gte=day_start,
        created__lt=day_start + timedelta(days=1)).count()

    # fill_rate 樣本＝OPENED 且非合成（合成列 carry 上次 detail 值，
    # 會掩蓋 parser 靜默失效）；dist 樣本＝OPENED 全體（與 distcheck 同基）
    fill_sample = list(
        HouseTS.objects.filter(**ts, deal_status=DealStatusType.OPENED)
        .exclude(is_synthesized=True).values(*FILL_RATE_FIELDS))
    fill_rate = {'n': len(fill_sample)}
    if fill_sample:
        for field in FILL_RATE_FIELDS:
            filled = sum(1 for row in fill_sample if is_filled(row[field]))
            fill_rate[field] = round(filled / len(fill_sample), 4)

    dist_rows = HouseTS.objects.filter(
        **ts, deal_status=DealStatusType.OPENED,
    ).values(
        'floor', 'total_floor', 'building_type', 'property_type',
        'is_rooftop', 'floor_ping', 'monthly_price', 'rough_coordinate',
    )
    generics = [{
        **row,
        'building_type': _enum_or_none(enums.BuildingType, row['building_type']),
        'property_type': _enum_or_none(enums.PropertyType, row['property_type']),
    } for row in dist_rows]

    return {
        **_base('detail', date_obj, source),
        'queue': _queue_stats(ts, RequestType.DETAIL, source),
        'counts': {
            'n_crawled': n_opened + n_closed + n_dealt,
            'n_opened': n_opened,
            'n_closed': n_closed,
            'n_dealt': n_dealt,
            'n_new_item': n_new,
        },
        'fill_rate': fill_rate,
        'dist': invariants(generics),
        'partitions': _partition_block('detail', date_obj),
    }


def build_deals_manifest(date_obj, source='live'):
    '''deals stage：當日寫入的 DEAL 列＝成交事件。

    成交日分佈（by_deal_date）看 lookback 窗口有沒有蓋滿；n_day_deal 中位數
    是 591「N天成交」的分佈哨兵。事件對未知物件不建檔，故這裡只數落地的。
    '''
    ts = _ts_of(date_obj)
    rows = list(HouseTS.objects.filter(**ts, deal_status=DealStatusType.DEAL)
                .values('deal_time', 'n_day_deal'))
    by_date = {}
    for row in rows:
        # 成交日是台灣日曆日（deals stage 寫 TST 午夜），依本地時區取日期，
        # 直接 .date() 會拿到 UTC 的前一天
        key = (timezone.localtime(row['deal_time']).date().isoformat()
               if row['deal_time'] else 'unknown')
        by_date[key] = by_date.get(key, 0) + 1
    n_days = sorted(r['n_day_deal'] for r in rows if r['n_day_deal'] is not None)
    median = n_days[len(n_days) // 2] if n_days else None
    return {
        **_base('deals', date_obj, source),
        'queue': _queue_stats(ts, RequestType.DEAL, source),
        'counts': {
            'n_events': len(rows),
            'n_with_deal_time': sum(1 for r in rows if r['deal_time']),
            'n_with_n_day_deal': len(n_days),
        },
        'by_deal_date': dict(sorted(by_date.items())),
        'dist': {
            'n': len(n_days),
            'median_n_day_deal': median,
        },
        'partitions': _partition_block('deals', date_obj),
    }


def build_snapshot_manifest(date_obj, source='live'):
    ts = _ts_of(date_obj)
    day_rows = HouseTS.objects.filter(**ts)
    n_total = day_rows.count()
    n_synth = day_rows.filter(is_synthesized=True).count()
    by_deal = dict(day_rows.values_list('deal_status').annotate(n=Count('id')))
    return {
        **_base('snapshot', date_obj, source),
        'counts': {
            'n_total': n_total,
            'n_synthesized': n_synth,
            'n_opened': by_deal.get(int(DealStatusType.OPENED), 0),
            'n_closed': by_deal.get(int(DealStatusType.NOT_FOUND), 0),
            'n_dealt': by_deal.get(int(DealStatusType.DEAL), 0),
        },
        'partitions': _partition_block('snapshot', date_obj),
    }


# ---- S3b：分區檔版 ---------------------------------------------------------------

_SNAPSHOT_COLS = [
    'vendor_house_id', 'deal_status', 'source', 'first_seen_at', 'deal_time', 'n_day_deal',
    'rough_address', 'floor', 'total_floor', 'building_type', 'property_type', 'is_rooftop',
    'floor_ping', 'monthly_price', 'rough_lat',
]
# detail 從不帶、list 才給的欄：fill_rate 改看同戶的 snapshot 列
_LIST_ONLY_FILL = ('rough_address',)


def _vendor_shorts():
    from rental.models import Vendor
    from rental.raws import vendor_dirname
    return [vendor_dirname(v.name) for v in Vendor.objects.all()]


class _DayPartitions:
    '''某日各 vendor 的 snapshot 列、今日 stub 出現過的戶、parsed 列（每戶最後一列）。
    一份 manifest 算一次；四個 builder 共用（build_all 走快取）。'''

    _cache = {}

    @classmethod
    def of(cls, date_obj):
        key = (date_obj.isoformat(), os.environ.get('TWRH_ARTIFACT_DIR'))
        if key not in cls._cache:
            cls._cache.clear()
            cls._cache[key] = cls(date_obj)
        return cls._cache[key]

    def __init__(self, date_obj):
        from rental import artifacts, contracts
        bucket = os.environ.get('TWRH_RAW_BUCKET')
        date_str = date_obj.isoformat()
        self.rows, self.in_list, self.parsed = [], set(), {}
        json_fields = {name for name, kind in contracts.PARSED_FIELDS if kind == contracts.JSON}
        for short in _vendor_shorts():
            self.rows.extend(artifacts.read_snapshot(short, date_str, bucket, _SNAPSHOT_COLS) or [])
            for stub in artifacts.read_list_stubs(short, date_str, bucket):
                self.in_list.add(stub['vendor_house_id'])
            for row in artifacts.read_parsed_rows(short, date_str, bucket):
                row.pop('vendor_extra', None)
                for name in json_fields & set(row):
                    if isinstance(row[name], str):
                        try:
                            row[name] = json.loads(row[name])
                        except ValueError:
                            pass
                prev = self.parsed.get(row['vendor_house_id'])
                if prev is None or (row.get('crawled_at') and prev.get('crawled_at')
                                    and row['crawled_at'] >= prev['crawled_at']):
                    self.parsed[row['vendor_house_id']] = row
        self.by_id = {r['vendor_house_id']: r for r in self.rows}
        self.opened = [r for r in self.rows if r['deal_status'] == int(DealStatusType.OPENED)]


def _partitions_list_manifest(date_obj, source):
    day = _DayPartitions.of(date_obj)
    ts = _ts_of(date_obj)
    in_list = day.in_list
    n_open = len(day.opened)
    n_in_list = sum(1 for r in day.opened if r['vendor_house_id'] in in_list)
    confirmed = [r for r in day.opened if r['source'] == 'detail']
    n_confirmed = len(confirmed)
    n_confirmed_in_list = sum(1 for r in confirmed if r['vendor_house_id'] in in_list)
    n_pending_absent = sum(1 for r in day.opened
                           if r['source'] != 'detail' and r['vendor_house_id'] not in in_list)
    return {
        **_base('list', date_obj, source),
        'queue': _queue_stats(ts, RequestType.LIST, source),
        'counts': {'n_in_list': len(in_list & set(day.by_id))},
        'capture': {
            'n_open': n_open,
            'n_open_in_list': n_in_list,
            'n_confirmed_open': n_confirmed,
            'n_confirmed_open_in_list': n_confirmed_in_list,
            'ratio': round(n_confirmed_in_list / n_confirmed, 4) if n_confirmed else None,
            'ratio_all_open': round(n_in_list / n_open, 4) if n_open else None,
            'n_pending_absent': n_pending_absent,
        },
        'partitions': _partition_block('list', date_obj),
    }


def _partitions_detail_manifest(date_obj, source):
    day = _DayPartitions.of(date_obj)
    ts = _ts_of(date_obj)
    by_deal = {}
    for r in day.rows:
        by_deal[r['deal_status']] = by_deal.get(r['deal_status'], 0) + 1
    n_opened = by_deal.get(int(DealStatusType.OPENED), 0)
    n_closed = by_deal.get(int(DealStatusType.NOT_FOUND), 0)
    n_dealt = by_deal.get(int(DealStatusType.DEAL), 0)

    n_new = sum(1 for r in day.rows if r['first_seen_at'] is not None
                and timezone.localtime(r['first_seen_at']).date() == date_obj)

    fill_sample = [p for p in day.parsed.values()
                   if p.get('deal_status') == int(DealStatusType.OPENED)]
    fill_rate = {'n': len(fill_sample)}
    if fill_sample:
        for field in FILL_RATE_FIELDS:
            key = 'rough_lat' if field == 'rough_coordinate' else field
            filled = 0
            for p in fill_sample:
                value = p.get(key)
                if value is None and field in _LIST_ONLY_FILL:
                    value = (day.by_id.get(p['vendor_house_id']) or {}).get(field)
                filled += 1 if is_filled(value) else 0
            fill_rate[field] = round(filled / len(fill_sample), 4)

    generics = [{
        'floor': r['floor'], 'total_floor': r['total_floor'],
        'building_type': _enum_or_none(enums.BuildingType, r['building_type']),
        'property_type': _enum_or_none(enums.PropertyType, r['property_type']),
        'is_rooftop': r['is_rooftop'], 'floor_ping': r['floor_ping'],
        'monthly_price': r['monthly_price'], 'rough_coordinate': r['rough_lat'],
    } for r in day.opened]

    return {
        **_base('detail', date_obj, source),
        'queue': _queue_stats(ts, RequestType.DETAIL, source),
        'counts': {
            'n_crawled': n_opened + n_closed + n_dealt,
            'n_opened': n_opened,
            'n_closed': n_closed,
            'n_dealt': n_dealt,
            'n_new_item': n_new,
        },
        'fill_rate': fill_rate,
        'dist': invariants(generics),
        'partitions': _partition_block('detail', date_obj),
    }


def _partitions_deals_manifest(date_obj, source):
    day = _DayPartitions.of(date_obj)
    ts = _ts_of(date_obj)
    rows = [r for r in day.rows if r['deal_status'] == int(DealStatusType.DEAL)]
    by_date = {}
    for row in rows:
        key = (timezone.localtime(row['deal_time']).date().isoformat()
               if row['deal_time'] else 'unknown')
        by_date[key] = by_date.get(key, 0) + 1
    n_days = sorted(r['n_day_deal'] for r in rows if r['n_day_deal'] is not None)
    return {
        **_base('deals', date_obj, source),
        'queue': _queue_stats(ts, RequestType.DEAL, source),
        'counts': {
            'n_events': len(rows),
            'n_with_deal_time': sum(1 for r in rows if r['deal_time']),
            'n_with_n_day_deal': len(n_days),
        },
        'by_deal_date': dict(sorted(by_date.items())),
        'dist': {'n': len(n_days), 'median_n_day_deal': n_days[len(n_days) // 2] if n_days else None},
        'partitions': _partition_block('deals', date_obj),
    }


def _partitions_snapshot_manifest(date_obj, source):
    day = _DayPartitions.of(date_obj)
    by_deal = {}
    for r in day.rows:
        by_deal[r['deal_status']] = by_deal.get(r['deal_status'], 0) + 1
    return {
        **_base('snapshot', date_obj, source),
        'counts': {
            'n_total': len(day.rows),
            'n_synthesized': sum(1 for r in day.rows if r['source'] != 'detail'),
            'n_opened': by_deal.get(int(DealStatusType.OPENED), 0),
            'n_closed': by_deal.get(int(DealStatusType.NOT_FOUND), 0),
            'n_dealt': by_deal.get(int(DealStatusType.DEAL), 0),
        },
        'partitions': _partition_block('snapshot', date_obj),
    }


_PARTITION_BUILDERS = {
    'list': _partitions_list_manifest, 'detail': _partitions_detail_manifest,
    'deals': _partitions_deals_manifest, 'snapshot': _partitions_snapshot_manifest,
}


def _dispatch(stage, db_builder):
    def build(date_obj, source='live'):
        # backfill 指的是「從 DB 回補歷史」；DB 停寫後只有分區檔這一條路
        if house_db():
            return db_builder(date_obj, source)
        return _PARTITION_BUILDERS[stage](date_obj, 'partitions' if source == 'live' else source)
    return build


build_list_manifest = _dispatch('list', build_list_manifest)
build_detail_manifest = _dispatch('detail', build_detail_manifest)
build_deals_manifest = _dispatch('deals', build_deals_manifest)
build_snapshot_manifest = _dispatch('snapshot', build_snapshot_manifest)

BUILDERS = {
    'list': build_list_manifest,
    'detail': build_detail_manifest,
    'deals': build_deals_manifest,
    'snapshot': build_snapshot_manifest,
}


def build_all(date_obj, source='live', base_dir=None):
    paths = []
    for stage, builder in BUILDERS.items():
        paths.append(write_manifest(builder(date_obj, source), base_dir))
    return paths
