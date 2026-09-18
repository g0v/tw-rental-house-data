'''snapshot 的 DB 端轉接（4c 過渡期；4f 去 Django 時整支退役）。

bootstrap_rows(vendor, day)：把某日的 DB 狀態摺成一份 snapshot 列——HouseTS 該日
bucket 的每一列（parsed 全欄）＋ House／HouseEtc 現值推出的 carry 欄。用途：
- 一階遞迴的起點：flow snapshot stage 發現前日 snapshot 不存在時，昨日由此摺出
  （2026-09-10 拍板「起點由 DB 摺出、往後日更」）
- #11 回填：更早的天數也能同法摺出（無 deal event 分區，deal_source 只能推）——
  但 House 現值對過去日不成立，carry='ts' 模式只填 HouseTS 該日列本身推得出的
  carry 欄（source、last_seen_at、days_absent=0 只在當日在 list 時、first_seen_at＝
  House.created、deal_source），其餘 carry 欄留 NULL（2026-09-10 拍板「回填無 carry 欄」；
  snapshotcheck 對過去日也只比這幾欄）

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
                            'author_key', 'vendor_extra')]


def etc_available():
    '''house_etc 還在不在（S2 起預設不在：停寫＋drop）。

    bootstrap_rows 只有兩件事要它——`last_fingerprint`（list_dict 的指紋）與
    `vendor_extra`（detail_dict）。S2 之後：指紋的來源是 list stub 分區的
    `fingerprint`（seed 判準已於 S1 改讀 snapshot carry 欄），vendor_extra 的來源是
    parsed 分區；bootstrap 只在「前日 snapshot 不存在」時才跑，那兩欄留 NULL 可接受
    （snapshotcheck 對過去日本來也只比 TS 推得出的欄）。
    回退＝環境 `TWRH_ETC_DB_WRITE=1`，與 pipeline 的開關同一個。
    '''
    import os
    return os.environ.get('TWRH_ETC_DB_WRITE', '0') == '1'


def _plain(name, value):
    if value is None:
        return None
    if name in _JSON_FIELDS:
        return value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False, sort_keys=True)
    return value


def ts_value_rows(vendor, day, hids, chunk=5000):
    '''某日 HouseTS 裡指定戶的 **parsed 值欄**（不含 carry 欄、不碰 HouseEtc）。

    `snapshotcarryfill --values` 用：只補少數幾百／千戶的 NULL 值欄，不該像
    `bootstrap_rows` 那樣把整日 85k 列連 `HouseEtc.detail_dict` 一起撈——2026-09-18
    實測那樣在 db.t4g.micro 上跑超過十分鐘（整份 detail JSON × 85k 列）。

    值取「那一天的 HouseTS 列」而非 House 現值：HouseTS 按日分桶，本身就是那天的狀態。
    '''
    out = {}
    hids = list(hids)
    for i in range(0, len(hids), chunk):
        # **一定要帶 hour**：唯一索引是 (year, month, day, hour, vendor, vendor_house_id)，
        # 少了 hour 就只能用 (y,m,d) 前綴＝撈當日 85k 列再過濾（2026-09-18 實測：不帶
        # hour 的版本在 db.t4g.micro 上跑 17 分鐘還沒完，而讀寫日檔本身只要 8 秒）。
        # hour 恆為 0（current_stepped_hour 以 24 為步進）
        qs = HouseTS.objects.filter(
            vendor=vendor, year=day.year, month=day.month, day=day.day, hour=0,
            vendor_house_id__in=hids[i:i + chunk]).select_related('author')
        for ts in qs.iterator(chunk_size=chunk):
            row = {name: _plain(name, getattr(ts, name)) for name in _TS_COPY}
            coord = ts.rough_coordinate
            if coord is not None:
                # 專案約定 Point(x=lat, y=lng)，見 contracts.parsed_row
                row['rough_lat'], row['rough_lng'] = float(coord.x), float(coord.y)
            row['author_key'] = contracts.short_hash(
                str(ts.author.truth)) if ts.author_id else None
            out[ts.vendor_house_id] = row
    return out


def bootstrap_rows(vendor, day, carry='house'):
    '''carry='house'：起點 bootstrap，carry 欄由 House／HouseEtc 現值推（只對「當日」正確）。
    carry='ts'：#11 回填過去日，carry 欄只取 HouseTS 該日列推得出的部分。'''
    if carry not in ('house', 'ts'):
        raise ValueError('carry must be house or ts')
    short = vendor_dirname(vendor.name)
    date_str = day.isoformat()
    day_start = timezone.make_aware(datetime.combine(day, time_cls.min))
    day_end = day_start + timedelta(days=1)

    ts_qs = HouseTS.objects.filter(
        vendor=vendor, year=day.year, month=day.month, day=day.day).select_related('author')
    ids = list(ts_qs.values_list('vendor_house_id', flat=True))
    houses, fingerprints, extras = {}, {}, {}
    for i in range(0, len(ids), 5000):
        chunk = ids[i:i + 5000]
        for h in House.objects.filter(vendor=vendor, vendor_house_id__in=chunk).only(
                'vendor_house_id', 'detail_crawled_at', 'list_crawled_at',
                'list_fingerprint_changed_at', 'created', 'deal_status'):
            houses[h.vendor_house_id] = h
        if not etc_available():
            continue
        for hid, list_dict, detail_dict in HouseEtc.objects.filter(
                vendor=vendor, vendor_house_id__in=chunk).values_list(
                'vendor_house_id', 'list_dict', 'detail_dict'):
            if list_dict:
                fingerprints[hid] = contracts.list_fingerprint(list_dict)
            # vendor_extra＝最新一次 detail 的 dict；detail_dict 是現值，只對「當日」bootstrap
            # 有意義（carry='ts' 回填過去日留 NULL，該日的 dict 在 parsed 分區／回補工具）
            if carry == 'house' and detail_dict:
                extras[hid] = _plain('vendor_extra', detail_dict)

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
        row['vendor_extra'] = extras.get(hid)

        detail_at = house.detail_crawled_at if house else None
        list_at = house.list_crawled_at if house else None
        fp_changed = house.list_fingerprint_changed_at if house else None
        in_list_today = ts.list_crawled_at is not None
        detail_today = detail_at is not None and day_start <= detail_at < day_end \
            and not ts.is_synthesized
        row['source'] = 'detail' if detail_today else 'list' if in_list_today else 'carry'
        row['first_seen_at'] = house.created if house else None
        if row['deal_status'] == snapshot.DEAL:
            row['deal_source'] = 'deals'
        if carry == 'ts':
            # 過去日：House 現值的 last_detail_at／指紋／list_crawled_at 都是「現在」的，
            # 不是那天的；只留該日列自己說得出的
            row['last_seen_at'] = ts.list_crawled_at
            row['days_absent'] = 0 if in_list_today else None
            rows.append(row)
            continue
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
        rows.append(row)
    return rows
