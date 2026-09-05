'''manifest 產生器（architecture-roadmap 1-2：觀測層單一機制）。

每個 stage 一份 `manifests/<date>/<stage>.json`——進出筆數、queue 終結
統計、逐欄填充率、分佈統計、版本。品質門檻＝`quality/assertions.yaml`
對 manifest 的斷言（qualitycheck）；日檢、月報、漂移偵測是同一機制的
不同時間窗。

manifest 是「對當日資料的純函數」：同一天重算結果相同，也因此可從 DB
回補歷史（1-3 的 9 月 backfill）——queue 終結統計在舊制（刪列＝完成）
下已丟，回補時缺項標 source=backfill、對應斷言由引擎降 advisory。

stage 對應現制（3-2 flow 收斂前的過渡分界）：
  list     — list 爬取＋L-B 捕獲哨兵
  detail   — detail 爬取＋解析（fill_rate／dist 都量在這）
  deals    — 「已成交」列表產出的成交事件（#229）：當日 TS 的 DEAL 列
  snapshot — syncstateful／synthts 之後的當日 TS 總覽
'''
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
    ——整節缺席，斷言引擎對缺 metric 的檢查自動降 advisory。'''
    if source == 'backfill':
        return None
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
    }


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
