'''manifest 產生器（twrhctl 版，無 Django）：django/crawlerrequest/manifests.py 的分區檔路徑。

S3b 起 house 三表停寫，manifest 只剩「由當日 snapshot／list stub／parsed 分區算出」這一條
（`source: partitions`）；DB 版 builder 與 request_ts 的 queue 統計隨 DB 退場不搬。
函數本體由原檔逐字取出（ast 切片），只把 timezone.localtime → twrhctl.tz.localtime、
vendors.all() → vendors.all(orm=False)——定義與欄位語意見原檔 docstring。
'''
import json
import os
from importlib.metadata import version, PackageNotFoundError

from scrapy_twrh.cli.runner import invariants
from scrapy_twrh.extensions.fill_rate import is_filled

from crawlerrequest.enums import RequestType
from crawlerrequest.manifest_files import (  # noqa: F401
    SCHEMA_VERSION, DEFAULT_DIR, manifest_dir, manifest_path,
    write_manifest, load_manifest, get_metric)
from rental import enums
from rental.enums import DealStatusType
from rental import vendors
from twrhctl import tz

try:
    PARSER_VERSION = version('scrapy-tw-rental-house')
except PackageNotFoundError:
    PARSER_VERSION = 'unknown'


def _queue_stats(ts, request_type, source):
    '''queue 終結統計：只剩檔案 queue（S4b 起 request_ts 沒人寫）。backfill＝整節缺席。'''
    if source == 'backfill':
        return None
    return _queue_stats_file(ts, request_type)


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


def _queue_stats_file(ts, request_type):
    from rental import filequeue
    from rental.raws import vendor_dirname
    date_str = '{year:04d}-{month:02d}-{day:02d}'.format(**ts)
    type_name = RequestType(request_type).name.lower()
    max_attempts = int(os.environ.get('TWRH_QUEUE_MAX_ATTEMPTS', 3))
    total = {'seeds': 0, 'done': 0, 'dead': 0, 'residue': 0}
    errors = {}
    for vendor in vendors.all(orm=False):
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
        'generated_at': tz.localtime().isoformat(),
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
    from rental.raws import vendor_dirname
    bucket = os.environ.get('TWRH_RAW_BUCKET')
    date_str = date_obj.isoformat()
    out = {}
    for vendor in vendors.all(orm=False):
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
        key = tz.localtime(r['deal_time']).date().isoformat() if r['deal_time'] else 'unknown'
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


_SNAPSHOT_COLS = [
    'vendor_house_id', 'deal_status', 'source', 'first_seen_at', 'deal_time', 'n_day_deal',
    'rough_address', 'floor', 'total_floor', 'building_type', 'property_type', 'is_rooftop',
    'floor_ping', 'monthly_price', 'rough_lat',
]


# detail 從不帶、list 才給的欄：fill_rate 改看同戶的 snapshot 列
_LIST_ONLY_FILL = ('rough_address',)


def _vendor_shorts():
    from rental.raws import vendor_dirname
    return [vendor_dirname(v.name) for v in vendors.all(orm=False)]


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
                and tz.localtime(r['first_seen_at']).date() == date_obj)

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
        key = (tz.localtime(row['deal_time']).date().isoformat()
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


def build_list_manifest(date_obj, source='live'):
    return _partitions_list_manifest(date_obj, 'partitions' if source == 'live' else source)


def build_detail_manifest(date_obj, source='live'):
    return _partitions_detail_manifest(date_obj, 'partitions' if source == 'live' else source)


def build_deals_manifest(date_obj, source='live'):
    return _partitions_deals_manifest(date_obj, 'partitions' if source == 'live' else source)


def build_snapshot_manifest(date_obj, source='live'):
    return _partitions_snapshot_manifest(date_obj, 'partitions' if source == 'live' else source)


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
