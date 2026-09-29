'''rerun_from_raws：從 raw 日包重跑 detail parser（architecture-roadmap 3-1）。

3-1 後 raw 的家在日包（raws/<vendor>/<date>.tar.zst＋index.jsonl，
production 在 S3 raw/ 樹；先 `aws s3 cp` 拉回本地目錄再跑——拍板：
debug／重算＝整包拉回，不做 S3 內部尋址）。修完 parser bug 後對歷史
日期重放，產出 parsed 分區（--parquet-dir），**不需重爬**。整份 dict 落在 vendor_extra。
S6 起沒有 DB：寫回 House 的 --commit 隨 DB 退場移除。

用法（在 twrh-dataset/ 下）：
  poetry run python tools/rerun_from_raws.py --from 2026-09-01 --to 2026-09-03
  poetry run python tools/rerun_from_raws.py --from 2026-09-04 --to 2026-09-05 \
      --parquet-dir artifacts        # 4b：重放結果直接落 parsed/<vendor>/<date>/rerun-<ts>.parquet
不給 --parquet-dir＝dry-run：只解析、統計成功率。
'''
import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import traceback
from datetime import datetime, timedelta

sys.path.append('{}/..'.format(os.path.dirname(os.path.realpath(__file__))))
sys.path.append('{}/../django'.format(os.path.dirname(os.path.realpath(__file__))))

from scrapy.http import Request, HtmlResponse
from scrapy_twrh.items import RawHouseItem, GenericHouseItem
from scrapy_twrh.spiders.rental591 import util

from scrapy_twrh.spiders.rental591 import Rental591Spider
from rental import contracts

DEFAULT_RAW_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', 'raws')


def iter_pack(pack_path):
    '''串流展開日包，yield (member_name, bytes)。'''
    proc = subprocess.Popen(
        ['zstd', '-dcq', pack_path], stdout=subprocess.PIPE)
    with tarfile.open(mode='r|', fileobj=proc.stdout) as tar:
        for info in tar:
            if not info.isfile():
                continue
            yield info.name, tar.extractfile(info).read()
    if proc.wait() != 0:
        raise RuntimeError('zstd failed on {}'.format(pack_path))


def rerun_page(spider, house_id, body):
    '''重放一頁 detail HTML，回傳 (detail_dict 或 None, GenericHouseItem 欄位 dict)。'''
    request = Request(**{
        **spider.gen_detail_request_args(util.DetailRequestMeta(id=house_id)),
        'callback': None,
    })
    response = HtmlResponse(
        request.url, status=200, request=request, body=body)
    detail_dict = None
    generic = {}
    for item in spider.default_parse_detail(response):
        if isinstance(item, RawHouseItem):
            if 'dict' in item and not item['is_list']:
                detail_dict = item['dict']
        elif isinstance(item, GenericHouseItem):
            generic.update(dict(item))
    return detail_dict, generic


def main():
    parser = argparse.ArgumentParser(
        description='Re-parse detail raw from daily packs through the current parser')
    parser.add_argument('--raw-dir', default=DEFAULT_RAW_DIR)
    parser.add_argument('--vendor', default='591 租屋網')
    parser.add_argument('--from', dest='date_from', required=True)
    parser.add_argument('--to', dest='date_to', required=True)
    parser.add_argument('--parquet-dir',
                        help='把重放結果寫成 parsed 分區檔：<dir>/parsed/<vendor>/<date>/rerun-<ts>.parquet（不需 DB）')
    options = parser.parse_args()
    run_tag = 'rerun-' + datetime.now().strftime('%Y%m%d%H%M%S')
    parser_version = None
    try:
        from importlib.metadata import version
        parser_version = version('scrapy-tw-rental-house')
    except Exception:
        pass

    # 日包目錄用 vendor 短名（raws/591/，與 S3 raw/591/ 對齊）
    vendor_dir = options.vendor.split()[0]
    # 用 package 端的 spider（parser 就住在那），不用 dataset 的 Detail591Spider
    # ——後者建構時會開 PersistQueue
    spider = Rental591Spider()
    current = datetime.strptime(options.date_from, '%Y-%m-%d').date()
    end = datetime.strptime(options.date_to, '%Y-%m-%d').date()

    total = ok = failed = written = missing_pack = 0
    while current <= end:
        date_str = current.isoformat()
        pack_path = os.path.join(
            options.raw_dir, vendor_dir, date_str + '.tar.zst')
        current += timedelta(days=1)
        if not os.path.exists(pack_path):
            missing_pack += 1
            print('{}: no pack, skip'.format(date_str))
            continue
        print('=== {} ==='.format(pack_path))
        parquet_rows = []
        for member, body in iter_pack(pack_path):
            if not member.endswith('.detail.html'):
                continue
            house_id = member.rsplit('.', 2)[0]
            total += 1
            try:
                detail_dict, generic = rerun_page(spider, house_id, body)
            except Exception:
                failed += 1
                print('parse error in {}'.format(member))
                traceback.print_exc()
                continue
            ok += 1
            if options.parquet_dir and generic:
                parquet_rows.append(contracts.coerce_row(contracts.parsed_row(
                    vendor_dir, house_id, date_str, run_tag, datetime.now().astimezone(),
                    parser_version, generic, vendor_extra=detail_dict), contracts.PARSED_FIELDS))
        if options.parquet_dir and parquet_rows:
            import pyarrow as pa
            import pyarrow.parquet as pq
            out_dir = os.path.join(options.parquet_dir, 'parsed', vendor_dir, date_str)
            os.makedirs(out_dir, exist_ok=True)
            out = os.path.join(out_dir, run_tag + '.parquet')
            pq.write_table(pa.Table.from_pylist(
                parquet_rows, schema=contracts.arrow_schema(contracts.PARSED_FIELDS)),
                out, compression='zstd')
            print('wrote {} rows -> {}'.format(len(parquet_rows), out))
            written += len(parquet_rows)

    print(json.dumps({
        'detail_pages': total, 'parsed_ok': ok, 'parse_failed': failed,
        'rows_written': written, 'missing_packs': missing_pack,
        'mode': 'parquet' if options.parquet_dir else 'dry-run',
    }, ensure_ascii=False))
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
