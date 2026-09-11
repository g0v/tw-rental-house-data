'''snapshot 的 DB 端轉接（4c 過渡期；4f 去 Django 時整支退役）。

bootstrap_rows(vendor, day)：把某日的 DB 狀態摺成一份 snapshot 列——HouseTS 該日
bucket 的每一列（parsed 全欄）＋ House／HouseEtc 現值推出的 carry 欄。用途：
- 一階遞迴的起點：flow snapshot stage 發現前日 snapshot 不存在時，昨日由此摺出
  （2026-09-10 拍板「起點由 DB 摺出、往後日更」）
- #11 回填：更早的天數也能同法摺出（無 deal event 分區，deal_source 只能推）

carry 欄的 DB 來源（與 rental/snapshot.fold 的語意對齊）：
- last_detail_at ＝ House.detail_crawled_at
- last_fingerprint ＝ sha1(price,title) of HouseEtc.list_dict（4a 前的指紋只存原文）
- fingerprint_at_last_detail ＝ last_fingerprint 若指紋未在上次 detail 之後變過
  （list_fingerprint_changed_at 空或 <= detail_crawled_at），否則 None——
  「None 且有 last_fingerprint」在 seed 判準裡視為指紋已變（保守：入 queue）
- days_absent ＝ 今日在 list 則 0，否則 today − date(House.list_crawled_at)
- last_seen_at ＝ House.list_crawled_at；first_seen_at ＝ House.created
- source ＝ detail（今日 detail 成功）／list（今日只在 list）／carry（synthts 合成或缺席）
- deal_source ＝ deals 若 DEAL（2026 改版後 DEAL 唯一來源是 deals stage）
'''
import json
from datetime import datetime, time as time_cls, timedelta

from django.utils import timezone

from rental import contracts, snapshot
from rental.models import House, HouseEtc, HouseTS
from rental.raws import vendor_dirname

_JSON_FIELDS = {name for name, kind in contracts.PARSED_FIELDS if kind == contracts.JSON}
_TS_COPY = [name for name, _ in contracts.PARSED_FIELDS
            if name not in ('vendor', 'vendor_house_id', 'date', 'run', 'crawled_at',
                            'parser_version', 'parsed_version', 'rough_lat', 'rough_lng',
                            'author_key')]


def _plain(name, value):
    if value is None:
        return None
    if name in _JSON_FIELDS:
        return value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False, sort_keys=True)
    return value


def bootstrap_rows(vendor, day):
    short = vendor_dirname(vendor.name)
    date_str = day.isoformat()
    day_start = timezone.make_aware(datetime.combine(day, time_cls.min))
    day_end = day_start + timedelta(days=1)

    ts_qs = HouseTS.objects.filter(
        vendor=vendor, year=day.year, month=day.month, day=day.day).select_related('author')
    ids = list(ts_qs.values_list('vendor_house_id', flat=True))
    houses, fingerprints = {}, {}
    for i in range(0, len(ids), 5000):
        chunk = ids[i:i + 5000]
        for h in House.objects.filter(vendor=vendor, vendor_house_id__in=chunk).only(
                'vendor_house_id', 'detail_crawled_at', 'list_crawled_at',
                'list_fingerprint_changed_at', 'created', 'deal_status'):
            houses[h.vendor_house_id] = h
        for hid, list_dict in HouseEtc.objects.filter(
                vendor=vendor, vendor_house_id__in=chunk).values_list(
                'vendor_house_id', 'list_dict'):
            if list_dict:
                fingerprints[hid] = contracts.list_fingerprint(list_dict)

    rows = []
    for ts in ts_qs.iterator(chunk_size=5000):
        hid = ts.vendor_house_id
        house = houses.get(hid)
        row = snapshot._blank(short, hid, date_str)
        for name in _TS_COPY:
            row[name] = _plain(name, getattr(ts, name))
        coord = ts.rough_coordinate
        if coord is not None:
            # 專案約定 Point(x=lat, y=lng)，見 contracts.parsed_row
            row['rough_lat'], row['rough_lng'] = float(coord.x), float(coord.y)
        row['author_key'] = contracts.short_hash(str(ts.author.truth)) if ts.author_id else None
        row['crawled_at'] = ts.crawled_at

        detail_at = house.detail_crawled_at if house else None
        list_at = house.list_crawled_at if house else None
        fp_changed = house.list_fingerprint_changed_at if house else None
        in_list_today = ts.list_crawled_at is not None
        detail_today = detail_at is not None and day_start <= detail_at < day_end \
            and not ts.is_synthesized
        row['source'] = 'detail' if detail_today else 'list' if in_list_today else 'carry'
        row['last_detail_at'] = detail_at
        row['last_fingerprint'] = fingerprints.get(hid)
        if detail_at is not None and (fp_changed is None or fp_changed <= detail_at):
            row['fingerprint_at_last_detail'] = row['last_fingerprint']
        row['last_seen_at'] = list_at
        if in_list_today:
            row['days_absent'] = 0
        elif list_at is not None:
            row['days_absent'] = max((day - timezone.localtime(list_at).date()).days, 0)
        else:
            row['days_absent'] = None
        row['first_seen_at'] = house.created if house else None
        if row['deal_status'] == snapshot.DEAL:
            row['deal_source'] = 'deals'
        rows.append(row)
    return rows
