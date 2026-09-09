'''parsedcheck：4b 雙寫對帳——當日 parsed parquet 逐欄對 DB（HouseTS 當日列）。

    manage.py parsedcheck [--date] [--vendor] [--strict] [--sample 5]

每戶取當日最晚一列 parquet（同日多輪重爬以後者為準，與 DB 覆寫語意一致），
與 HouseTS 該日 bucket 的列比：
- 純爬取欄（價格／格局／區域／設施…）：兩邊都有值時必須相等（enum 比 int、
  JSON 比正規化字串、座標比 lat/lng——DB Point 是 x=lat／y=lng 的專案約定、
  author 比雜湊、float 比 isclose）；parquet 為 NULL 而 DB 有值＝該欄不是 detail
  解析產出（例如 imgs 來自 list），另計 `parquet_null_db_set`，不算錯
- 狀態欄 deal_status／deal_time／n_day_deal：只計數不算錯——deals stage／
  syncstateful 會在 detail 之後改 DB，parquet 記的是 detail 當下
- crawled_at：容忍 10 秒（pipeline 兩次 timezone.now()）
量的對照：parquet 去重戶數 vs 當日 detail_crawled_at 落在今日的 House 數。
預設 advisory（exit 0）；--strict 有 mismatch 即 exit 1。
'''
import json
import math
import os
import sys
from datetime import date as date_cls, datetime, time as time_cls, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from rental import artifacts, contracts
from rental.models import House, HouseTS, Vendor
from rental.raws import vendor_dirname

STATE_FIELDS = ('deal_status', 'deal_time', 'n_day_deal')
SKIP_FIELDS = {'vendor', 'vendor_house_id', 'date', 'run', 'parser_version',
               'parsed_version', 'crawled_at'}
JSON_FIELDS = {name for name, kind in contracts.PARSED_FIELDS if kind == contracts.JSON}


def norm_db(name, value):
    if value is None:
        return None
    if name in JSON_FIELDS:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if hasattr(value, 'isoformat'):
        return value
    return value


def equal(name, a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-6)
        except (TypeError, ValueError):
            return False
    if hasattr(a, 'isoformat') and hasattr(b, 'isoformat'):
        return abs((a - b).total_seconds()) < 1
    return a == b


class Command(BaseCommand):
    help = 'Compare the day\'s parsed parquet rows against HouseTS field by field'

    def add_arguments(self, parser):
        parser.add_argument('--date')
        parser.add_argument('--vendor', default='591 租屋網')
        parser.add_argument('--strict', action='store_true')
        parser.add_argument('--sample', type=int, default=5)

    def handle(self, *_args, **options):
        if options['date']:
            try:
                day = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('--date 需為 YYYY-MM-DD')
        else:
            env = os.environ.get('TWRH_TARGET_DATE')
            day = datetime.strptime(env, '%Y-%m-%d').date() if env else date_cls.today()
        vendor = Vendor.objects.get(name=options['vendor'])
        short = vendor_dirname(vendor.name)
        bucket = os.environ.get('TWRH_RAW_BUCKET')

        rows = artifacts.read_parsed_rows(short, day.isoformat(), bucket)
        if not rows:
            print('parsedcheck: no parsed partitions for {} — skip'.format(day))
            return
        latest = {}
        for row in rows:
            hid = row['vendor_house_id']
            if hid not in latest or (row['crawled_at'] or datetime.min.replace(
                    tzinfo=timezone.utc)) >= (latest[hid]['crawled_at'] or datetime.min.replace(
                        tzinfo=timezone.utc)):
                latest[hid] = row

        day_start = timezone.make_aware(datetime.combine(day, time_cls.min))
        n_db_detail = House.objects.filter(
            vendor=vendor, detail_crawled_at__gte=day_start,
            detail_crawled_at__lt=day_start + timedelta(days=1)).count()

        ts_rows = {}
        ids = list(latest)
        for i in range(0, len(ids), 5000):
            chunk = ids[i:i + 5000]
            for ts in HouseTS.objects.filter(
                    vendor=vendor, year=day.year, month=day.month, day=day.day,
                    vendor_house_id__in=chunk).select_related('author'):
                ts_rows[ts.vendor_house_id] = ts

        compare_fields = [name for name, _ in contracts.PARSED_FIELDS
                          if name not in SKIP_FIELDS and name not in STATE_FIELDS
                          and name not in ('rough_lat', 'rough_lng', 'author_key')]
        mismatch = {}
        samples = {}
        null_vs_set = {}
        state_diff = {name: 0 for name in STATE_FIELDS}
        missing = []
        matched = 0
        crawled_drift = 0

        def note(name, hid, a, b):
            mismatch[name] = mismatch.get(name, 0) + 1
            if len(samples.setdefault(name, [])) < options['sample']:
                samples[name].append((hid, a, b))

        for hid, row in latest.items():
            ts = ts_rows.get(hid)
            if ts is None:
                missing.append(hid)
                continue
            ok = True
            for name in compare_fields:
                db_value = norm_db(name, getattr(ts, name))
                if row.get(name) is None and db_value is not None:
                    null_vs_set[name] = null_vs_set.get(name, 0) + 1
                    continue
                if not equal(name, row.get(name), db_value):
                    note(name, hid, row.get(name), db_value)
                    ok = False
            coord = ts.rough_coordinate
            # 專案約定：Point(x=lat, y=lng)，見 rental/contracts.parsed_row
            lat, lng = (coord.x, coord.y) if coord is not None else (None, None)
            if row.get('rough_lat') is None and lat is not None:
                null_vs_set['rough_coordinate'] = null_vs_set.get('rough_coordinate', 0) + 1
            elif not (equal('rough_lat', row.get('rough_lat'), lat)
                      and equal('rough_lng', row.get('rough_lng'), lng)):
                note('rough_coordinate', hid, (row.get('rough_lat'), row.get('rough_lng')), (lat, lng))
                ok = False
            author_key = contracts.short_hash(str(ts.author.truth)) if ts.author_id else None
            if row.get('author_key') is None and author_key is not None:
                null_vs_set['author_key'] = null_vs_set.get('author_key', 0) + 1
            elif row.get('author_key') != author_key:
                note('author_key', hid, row.get('author_key'), author_key)
                ok = False
            for name in STATE_FIELDS:
                if not equal(name, row.get(name), getattr(ts, name)):
                    state_diff[name] += 1
            if row.get('crawled_at') and ts.crawled_at and \
                    abs((row['crawled_at'] - ts.crawled_at).total_seconds()) > 10:
                crawled_drift += 1
            if ok:
                matched += 1

        report = {
            'date': day.isoformat(),
            'parquet_rows': len(rows),
            'houses': len(latest),
            'db_detail_today': n_db_detail,
            'matched': matched,
            'missing_in_db': len(missing),
            'mismatch_by_field': mismatch,
            'parquet_null_db_set': null_vs_set,
            'state_fields_changed_after_detail': state_diff,
            'crawled_at_drift_gt10s': crawled_drift,
        }
        agree = not mismatch and not missing
        print('parsedcheck: {} — {}'.format('AGREE' if agree else 'DIFF',
                                            json.dumps(report, ensure_ascii=False, default=str)))
        for name, items in samples.items():
            print('parsedcheck: {} sample: {}'.format(name, items))
        if missing:
            print('parsedcheck: missing in DB (sample): {}'.format(missing[:options['sample']]))
        if not agree and options['strict']:
            sys.exit(1)
