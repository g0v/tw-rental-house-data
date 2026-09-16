#!/usr/bin/env python3
'''backfill_vendor_extra：把 vendor_extra（整份 detail_dict）回補進 vendor_extra 上線前的
parsed 分區與 snapshot（2026-09-14 拍板「記得回補這段時間缺的 etc」）。

    python tools/backfill_vendor_extra.py --from 2026-09-04 --to 2026-09-16 [--upload] [--force]
    python tools/backfill_vendor_extra.py --snapshot 2026-09-16 [--from 2026-09-04] [--upload]

parsed 回補（--from/--to）：每一天
  1. 取當日 raw 日包（本地 raws/<vendor>/<date>.tar.zst，沒有就從 S3 raw/<vendor>/ 拉回），
     用現行 parser 重放每一頁 detail → detail_dict（同一版式、同一 parser，dict 與當時 pipeline
     寫進 house_etc 的一致；9/4 之後的頁都是 2026 版式）。
  2. 當日每個 parsed 分區檔（run／sweep-HHMM；本地沒有就從 S3 拉）逐列補 vendor_extra：
     只補 NULL（--force 連已有的也覆蓋）、404／拒解析列不補。列本身不重算、parsed_version 不動
     ——這是「加一欄」不是「重算歷史」。同一戶同日多列（日跑＋sweep）拿同一份 dict：日包是當日
     聯集、只留最後一爬，早一輪那列的 dict 可能是稍新的版本，記在此、不另處理。
  3. --upload 覆寫 S3 同 key（parsed 分區「永不改寫別輪」的例外：人工顯式觸發的回補；
     bucket 有 versioning，舊版本 30 天內可還原）。

snapshot 回補（--snapshot DATE）：把 snapshot/<vendor>/<DATE>.parquet 的 vendor_extra NULL 列，
用 --from..DATE 期間 parsed 分區裡該戶最後一次（crawled_at 最大）的 vendor_extra 補上（parsed 先回補
完再跑）。用途＝上線當天的 provisional／隔日 final 起點：之後 fold 自己會沿用。不需要 DB。

不連 DB（只用 package 端 spider 與 rental.artifacts／contracts 的純函數；load_django 只為了
import 路徑與 settings，同 rerun_from_raws 的 dry-run）。
'''
import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..'))
from tools.utils import load_django  # noqa: E402
load_django()

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from rental import artifacts, contracts  # noqa: E402
from rental.raws import raw_dir  # noqa: E402


def fill_vendor_extra(table, extra_by_hid, force=False):
    '''純函數：parquet table（parsed 或 snapshot 列）+ {house_id: json 字串} → (新 table, 補了幾列)。
    沒有 vendor_extra 欄就加；有則只補 NULL（force 全覆蓋）；404 關閉列（closure）不補。'''
    names = table.column_names
    hids = table.column('vendor_house_id').to_pylist()
    old = table.column('vendor_extra').to_pylist() if 'vendor_extra' in names else [None] * len(hids)
    closure = _closure_mask(table)
    out, filled = [], 0
    for i, hid in enumerate(hids):
        value = old[i]
        if (value is None or force) and not closure[i] and extra_by_hid.get(hid):
            value = extra_by_hid[hid]
            filled += 1
        out.append(value)
    column = pa.array(out, type=pa.string())
    if 'vendor_extra' in names:
        table = table.set_column(names.index('vendor_extra'), 'vendor_extra', column)
    else:
        # 契約順序：vendor_extra 在 parsed_version 之前（parsed）／imgs 之後（snapshot）
        anchor = names.index('parsed_version') if 'parsed_version' in names else names.index('imgs') + 1
        table = table.add_column(anchor, 'vendor_extra', column)
    return table, filled


def _closure_mask(table):
    '''pipeline 對 404／拒解析寫的列：deal_status=NOT_FOUND 且 detail 欄全 NULL。'''
    if 'deal_status' not in table.column_names:
        return [False] * table.num_rows
    status = table.column('deal_status').to_pylist()
    probe = [c for c in ('monthly_price', 'floor_ping', 'top_region') if c in table.column_names]
    probes = [table.column(c).to_pylist() for c in probe]
    return [s == 1 and all(p[i] is None for p in probes) for i, s in enumerate(status)]


def _rewrite(path, table):
    tmp = path + '.tmp'
    pq.write_table(table, tmp, compression='zstd')
    os.replace(tmp, path)


def pack_path_for(vendor_short, date_str, bucket):
    path = os.path.join(raw_dir(), vendor_short, date_str + '.tar.zst')
    if os.path.exists(path) or not bucket:
        return path if os.path.exists(path) else None
    import boto3
    from botocore.exceptions import ClientError
    s3 = boto3.client('s3')
    key = 'raw/{}/{}.tar.zst'.format(vendor_short, date_str)
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError as err:
        if err.response['Error']['Code'] in ('404', 'NoSuchKey', 'NotFound'):
            return None
        raise
    os.makedirs(os.path.dirname(path), exist_ok=True)
    s3.download_file(bucket, key, path)
    print('    pulled s3://{}/{}'.format(bucket, key))
    return path


def extras_from_pack(pack_path):
    '''日包 → {house_id: vendor_extra json}。用 package 端 spider 重放（同 rerun_from_raws）。'''
    from tools.rerun_from_raws import iter_pack, rerun_page
    from scrapy_twrh.spiders.rental591 import Rental591Spider
    spider = Rental591Spider()
    out, pages, failed = {}, 0, 0
    for member, body in iter_pack(pack_path):
        if not member.endswith('.detail.html'):
            continue
        pages += 1
        house_id = os.path.basename(member).rsplit('.', 2)[0]   # <hid>.detail.html（容忍 ./ 前綴）
        try:
            detail_dict, _fields, _generic = rerun_page(spider, house_id, body)
        except Exception as err:  # noqa: BLE001
            failed += 1
            print('    parse error {}: {}'.format(member, err))
            continue
        if detail_dict:
            out[house_id] = contracts.coerce_value(detail_dict, contracts.JSON)
    print('    {} detail pages → {} dicts ({} parse errors)'.format(pages, len(out), failed))
    return out


def backfill_parsed(vendor_short, date_str, bucket, upload, force):
    pack = pack_path_for(vendor_short, date_str, bucket)
    if pack is None:
        print('{}: no raw pack — skip'.format(date_str))
        return
    files = artifacts.partition_files('parsed', vendor_short, date_str, bucket)
    if not files:
        print('{}: no parsed partitions — skip'.format(date_str))
        return
    print('=== {}: {} parsed partition(s), pack {}'.format(date_str, len(files), pack))
    extras = extras_from_pack(pack)
    for path in files:
        table = pq.read_table(path)
        table, filled = fill_vendor_extra(table, extras, force=force)
        n_null = table.column('vendor_extra').null_count
        _rewrite(path, table)
        run = os.path.basename(path).rsplit('.', 1)[0]
        print('    {}: {} rows, filled {}, still NULL {} (closure／no raw)'.format(
            run, table.num_rows, filled, n_null))
        if upload and bucket:
            artifacts.upload(bucket, 'parsed', vendor_short, date_str, run, path)


def latest_extras(vendor_short, date_from, date_to, bucket):
    '''--from..--to 期間 parsed 分區裡每戶最後一次（crawled_at 最大）的 vendor_extra。'''
    best = {}
    day = date_from
    while day <= date_to:
        for path in artifacts.partition_files('parsed', vendor_short, day.isoformat(), bucket):
            table = pq.read_table(path, columns=['vendor_house_id', 'crawled_at', 'vendor_extra']) \
                if 'vendor_extra' in pq.read_schema(path).names else None
            if table is None:
                continue
            for hid, at, extra in zip(*(table.column(c).to_pylist()
                                        for c in ('vendor_house_id', 'crawled_at', 'vendor_extra'))):
                if extra and (hid not in best or at >= best[hid][0]):
                    best[hid] = (at, extra)
        day += timedelta(days=1)
    return {hid: extra for hid, (_at, extra) in best.items()}


def backfill_snapshot(vendor_short, date_str, date_from, bucket, upload):
    path = artifacts.snapshot_path(vendor_short, date_str)
    if not os.path.exists(path):
        if not (bucket and artifacts.snapshot_exists(vendor_short, date_str, bucket)):
            print('{}: no snapshot — skip'.format(date_str))
            return
        artifacts._fetch_snapshot(vendor_short, date_str, bucket)
    extras = latest_extras(vendor_short, date_from, datetime.strptime(date_str, '%Y-%m-%d').date(), bucket)
    table = pq.read_table(path)
    table, filled = fill_vendor_extra(table, extras)
    _rewrite(path, table)
    print('=== snapshot {}: {} rows, filled {}, still NULL {} (from {} parsed extras since {})'.format(
        date_str, table.num_rows, filled, table.column('vendor_extra').null_count, len(extras), date_from))
    if upload and bucket:
        artifacts.upload_snapshot(bucket, vendor_short, date_str, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--vendor', default='591')
    parser.add_argument('--from', dest='date_from', default='2026-09-04',
                        help='raw 日包起日（rawpack 自 2026-09-04 起）')
    parser.add_argument('--to', dest='date_to')
    parser.add_argument('--snapshot', help='只補這一天的 snapshot（parsed 先回補完）')
    parser.add_argument('--bucket', default=os.environ.get('TWRH_RAW_BUCKET'))
    parser.add_argument('--upload', action='store_true', help='改完覆寫 S3 同 key')
    parser.add_argument('--force', action='store_true', help='parsed 已有 vendor_extra 也覆蓋')
    options = parser.parse_args()
    date_from = datetime.strptime(options.date_from, '%Y-%m-%d').date()
    if options.snapshot:
        backfill_snapshot(options.vendor, options.snapshot, date_from, options.bucket, options.upload)
        return
    if not options.date_to:
        parser.error('--to 或 --snapshot 擇一')
    day, end = date_from, datetime.strptime(options.date_to, '%Y-%m-%d').date()
    while day <= end:
        backfill_parsed(options.vendor, day.isoformat(), options.bucket, options.upload, options.force)
        day += timedelta(days=1)


if __name__ == '__main__':
    main()
