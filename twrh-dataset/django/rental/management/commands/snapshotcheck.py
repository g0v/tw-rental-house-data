'''snapshotcheck：4c 雙寫對帳——某日 snapshot parquet 逐戶逐欄對 DB（HouseTS 該日列＋House carry 欄）。

    manage.py snapshotcheck [--date] [--vendor] [--strict] [--sample 5]

戶集合：snapshot 每戶一列 vs HouseTS 該日 bucket 每戶一列——synthts 之後兩邊都該是
「每個 open 戶每日一列＋當日有事件的已關閉戶」；只在一邊的戶分來源（snapshot 的
source）／狀態（DB 的 deal_status，合成列另標）計數。共同戶逐欄：
- parsed 欄：同 parsedcheck 的比法（enum 比 int、JSON 比正規化字串、座標依專案約定
  Point x=lat／y=lng、author 比雜湊、float isclose）；一邊 NULL 一邊有值不算錯、另計：
  `snapshot_null_db_set`（stub 只帶 list 子集，新戶 list 列比 DB 稀疏——4a 契約待擴）、
  `db_null_snapshot_set`（DB 的已關閉／成交列只帶事件欄，snapshot 攜帶昨日狀態）。
  imgs 不比：2026-09-10 拍板 snapshot 的 imgs＝detail 全尺寸、只在 list 時不動，DB 每日被
  list 縮圖蓋掉，兩邊刻意不同
- 狀態欄 deal_status／deal_time／n_day_deal：這裡算錯（export 要讀它）——deals 分區缺、
  推導語意不同都在 `state_mismatch` 現形
- carry 欄：檢查「當日」（＝TWRH_TARGET_DATE）時對 House 現值：last_detail_at↔
  detail_crawled_at、last_seen_at↔list_crawled_at、first_seen_at↔created、days_absent、
  last_fingerprint↔sha1(price,title) of HouseEtc.list_dict（carry_mode=house）；檢查過去日
  （昨日 final）時 House 現值已被今日改寫，只對 HouseTS 該列可推的兩項：在 list ⇒
  last_seen_at≈list_crawled_at 且 days_absent==0（carry_mode=ts）。時間欄容忍 10 秒
  （pipeline 多次 timezone.now()）。first_seen_at 只在 snapshot 比 House.created 早才算錯
  ——重刊戶在 snapshot 血統裡重新起算是設計內的（n_day_deal 推導以此為起點）。只由 deal
  事件生出的空白列（昨日不在 snapshot：早已關閉的戶成交）沒有 carry 可比，另計
  `deal_only_rows`；House 從未在 list 的戶 days_absent 不可知、不比。
AGREE＝兩邊戶集合相等且零 mismatch。預設 advisory（exit 0）；--strict 有差即 exit 1。
'''
import json
import os
import sys
from datetime import date as date_cls, datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from rental import artifacts, contracts
from rental.management.commands.parsedcheck import STATE_FIELDS, equal, norm_db
from rental.models import House, HouseEtc, HouseTS, Vendor
from rental.raws import vendor_dirname

CARRY_FIELDS = {name for name, _ in contracts.SNAPSHOT_CARRY_FIELDS}
SKIP_FIELDS = {'vendor', 'vendor_house_id', 'date', 'crawled_at', 'parser_version',
               'rough_lat', 'rough_lng', 'author_key', 'imgs'} | CARRY_FIELDS
COMPARE_FIELDS = [name for name, _ in contracts.SNAPSHOT_FIELDS
                  if name not in SKIP_FIELDS and name not in STATE_FIELDS]
STATUS_NAME = {0: 'opened', 1: 'closed', 2: 'dealt'}
TOLERANCE_S = 10


def close(a, b, tolerance=TOLERANCE_S):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs((a - b).total_seconds()) <= tolerance


def _target_date():
    env = os.environ.get('TWRH_TARGET_DATE')
    return datetime.strptime(env, '%Y-%m-%d').date() if env else date_cls.today()


class Command(BaseCommand):
    help = 'Compare a day\'s snapshot parquet against HouseTS/House field by field'

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
            day = _target_date()
        vendor = Vendor.objects.get(name=options['vendor'])
        short = vendor_dirname(vendor.name)
        bucket = os.environ.get('TWRH_RAW_BUCKET')
        date_str = day.isoformat()

        rows = artifacts.read_snapshot(short, date_str, bucket)
        if rows is None:
            print('snapshotcheck: no snapshot for {} — skip'.format(day))
            return
        snap = {r['vendor_house_id']: r for r in rows}
        n_snapshot = len(rows)
        del rows

        carry_mode = 'house' if day == _target_date() else 'ts'
        houses, fingerprints = {}, {}
        if carry_mode == 'house':
            ids = list(snap)
            for i in range(0, len(ids), 5000):
                chunk = ids[i:i + 5000]
                for hid, detail_at, list_at, created in House.objects.filter(
                        vendor=vendor, vendor_house_id__in=chunk).values_list(
                        'vendor_house_id', 'detail_crawled_at', 'list_crawled_at', 'created'):
                    houses[hid] = (detail_at, list_at, created)
                for hid, list_dict in HouseEtc.objects.filter(
                        vendor=vendor, vendor_house_id__in=chunk).values_list(
                        'vendor_house_id', 'list_dict'):
                    if list_dict:
                        fingerprints[hid] = contracts.list_fingerprint(list_dict)

        mismatch, state_mismatch, carry_mismatch = {}, {}, {}
        samples = {}
        null_vs_set, db_null = {}, {}
        only_db = {}
        matched = n_db = deal_only = 0

        def note(bucket_dict, name, hid, a, b):
            bucket_dict[name] = bucket_dict.get(name, 0) + 1
            if len(samples.setdefault(name, [])) < options['sample']:
                samples[name].append((hid, a, b))

        ts_qs = HouseTS.objects.filter(
            vendor=vendor, year=day.year, month=day.month, day=day.day).select_related('author')
        for ts in ts_qs.iterator(chunk_size=5000):
            n_db += 1
            hid = ts.vendor_house_id
            row = snap.pop(hid, None)
            if row is None:
                key = STATUS_NAME.get(int(ts.deal_status), str(ts.deal_status))
                if ts.is_synthesized:
                    key += '/synthesized'
                only_db[key] = only_db.get(key, 0) + 1
                continue
            ok = True
            for name in COMPARE_FIELDS:
                db_value = norm_db(name, getattr(ts, name))
                if row.get(name) is None and db_value is not None:
                    null_vs_set[name] = null_vs_set.get(name, 0) + 1
                    continue
                if db_value is None and row.get(name) is not None:
                    db_null[name] = db_null.get(name, 0) + 1
                    continue
                if not equal(name, row.get(name), db_value):
                    note(mismatch, name, hid, row.get(name), db_value)
                    ok = False
            coord = ts.rough_coordinate
            # 專案約定：Point(x=lat, y=lng)，見 rental/contracts.parsed_row
            lat, lng = (coord.x, coord.y) if coord is not None else (None, None)
            if row.get('rough_lat') is None and lat is not None:
                null_vs_set['rough_coordinate'] = null_vs_set.get('rough_coordinate', 0) + 1
            elif lat is None and row.get('rough_lat') is not None:
                db_null['rough_coordinate'] = db_null.get('rough_coordinate', 0) + 1
            elif not (equal('rough_lat', row.get('rough_lat'), lat)
                      and equal('rough_lng', row.get('rough_lng'), lng)):
                note(mismatch, 'rough_coordinate', hid,
                     (row.get('rough_lat'), row.get('rough_lng')), (lat, lng))
                ok = False
            author_key = contracts.short_hash(str(ts.author.truth)) if ts.author_id else None
            if row.get('author_key') is None and author_key is not None:
                null_vs_set['author_key'] = null_vs_set.get('author_key', 0) + 1
            elif author_key is None and row.get('author_key') is not None:
                db_null['author_key'] = db_null.get('author_key', 0) + 1
            elif row.get('author_key') != author_key:
                note(mismatch, 'author_key', hid, row.get('author_key'), author_key)
                ok = False
            for name in STATE_FIELDS:
                if not equal(name, row.get(name), getattr(ts, name)):
                    note(state_mismatch, name, hid, row.get(name), getattr(ts, name))
                    ok = False

            blank_born = row.get('last_seen_at') is None and row.get('first_seen_at') is None
            if blank_born:
                deal_only += 1
            elif carry_mode == 'house':
                house = houses.get(hid)
                if house is not None:
                    detail_at, list_at, created = house
                    if not close(row.get('last_detail_at'), detail_at):
                        note(carry_mismatch, 'last_detail_at', hid, row.get('last_detail_at'), detail_at)
                        ok = False
                    if not close(row.get('last_seen_at'), list_at):
                        note(carry_mismatch, 'last_seen_at', hid, row.get('last_seen_at'), list_at)
                        ok = False
                    first = row.get('first_seen_at')
                    if first is not None and created is not None and \
                            (created - first).total_seconds() > 60:
                        note(carry_mismatch, 'first_seen_at', hid, first, created)
                        ok = False
                    if ts.list_crawled_at is not None:
                        expected_absent = 0
                    elif list_at is not None:
                        expected_absent = max((day - timezone.localtime(list_at).date()).days, 0)
                    else:
                        expected_absent = row.get('days_absent')   # 從未在 list：不可知
                    if row.get('days_absent') != expected_absent:
                        note(carry_mismatch, 'days_absent', hid, row.get('days_absent'), expected_absent)
                        ok = False
                    fp = fingerprints.get(hid)
                    if fp is not None and row.get('last_fingerprint') != fp:
                        note(carry_mismatch, 'last_fingerprint', hid, row.get('last_fingerprint'), fp)
                        ok = False
            elif ts.list_crawled_at is not None:
                if not close(row.get('last_seen_at'), ts.list_crawled_at):
                    note(carry_mismatch, 'last_seen_at', hid, row.get('last_seen_at'), ts.list_crawled_at)
                    ok = False
                if row.get('days_absent') != 0:
                    note(carry_mismatch, 'days_absent', hid, row.get('days_absent'), 0)
                    ok = False
            if ok:
                matched += 1

        only_snapshot = {}
        for row in snap.values():
            key = row.get('source') or 'unknown'
            only_snapshot[key] = only_snapshot.get(key, 0) + 1

        report = {
            'date': date_str,
            'carry_mode': carry_mode,
            'snapshot_rows': n_snapshot,
            'db_rows': n_db,
            'matched': matched,
            'only_db': only_db,
            'only_snapshot': only_snapshot,
            'mismatch_by_field': mismatch,
            'state_mismatch': state_mismatch,
            'carry_mismatch': carry_mismatch,
            'deal_only_rows': deal_only,
            'snapshot_null_db_set': null_vs_set,
            'db_null_snapshot_set': db_null,
        }
        agree = not (only_db or only_snapshot or mismatch or state_mismatch or carry_mismatch)
        print('snapshotcheck: {} — {}'.format('AGREE' if agree else 'DIFF',
                                              json.dumps(report, ensure_ascii=False, default=str)))
        for name, items in samples.items():
            print('snapshotcheck: {} sample: {}'.format(name, items))
        if not agree and options['strict']:
            sys.exit(1)
