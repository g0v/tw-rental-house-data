'''rerun_from_raws：從 raw 日包重跑 detail parser（architecture-roadmap 3-1）。

3-1 後 raw 的家在日包（raws/<vendor>/<date>.tar.zst＋index.jsonl，
production 在 S3 raw/ 樹；先 `aws s3 cp` 拉回本地目錄再跑——拍板：
debug／重算＝整包拉回，不做 S3 內部尋址）。修完 parser bug 後對歷史
日期重放，更新 HouseEtc.detail_dict 與 House 欄位，**不需重爬**。

DB 尚存 raw 的過渡期（cutover 前），舊列仍可用 rerun_detail_raw.py
的 DB 模式；本工具只讀日包，是 cutover 後的唯一重放路徑。

用法（在 twrh-dataset/ 下）：
  poetry run python tools/rerun_from_raws.py --from 2026-09-01 --to 2026-09-03
  poetry run python tools/rerun_from_raws.py --from 2026-09-01 --to 2026-09-01 --commit
預設 dry-run：只解析、統計成功率，不寫 DB。
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

from tools.utils import load_django
load_django()

from django.contrib.gis.geos import Point
from django.db import transaction
from scrapy.http import Request, HtmlResponse
from scrapy_twrh.items import RawHouseItem, GenericHouseItem
from scrapy_twrh.spiders.rental591 import util

from crawler.spiders.detail591_spider import Detail591Spider
from rental.models import Author, House, HouseEtc, Vendor

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
    '''重放一頁 detail HTML，回傳 (detail_dict 或 None, house 欄位 dict)。'''
    request = Request(**{
        **spider.gen_detail_request_args(util.DetailRequestMeta(id=house_id)),
        'callback': None,
    })
    response = HtmlResponse(
        request.url, status=200, request=request, body=body)
    detail_dict = None
    house_fields = {}
    for item in spider.default_parse_detail(response):
        if isinstance(item, RawHouseItem):
            if 'dict' in item and not item['is_list']:
                detail_dict = item['dict']
        elif isinstance(item, GenericHouseItem):
            fields = dict(item)
            fields.pop('vendor', None)
            fields.pop('vendor_house_id', None)
            # 歷史 raw 不得回滾現況的 sticky 狀態（重放≠重爬）
            fields.pop('deal_status', None)
            # 與 pipeline 同款轉換
            if 'rough_coordinate' in fields:
                fields['rough_coordinate'] = Point(
                    fields['rough_coordinate'], srid=4326)
            house_fields.update(fields)
    return detail_dict, house_fields


def main():
    parser = argparse.ArgumentParser(
        description='Re-parse detail raw from daily packs through the current parser')
    parser.add_argument('--raw-dir', default=DEFAULT_RAW_DIR)
    parser.add_argument('--vendor', default='591 租屋網')
    parser.add_argument('--from', dest='date_from', required=True)
    parser.add_argument('--to', dest='date_to', required=True)
    parser.add_argument('--commit', action='store_true',
                        help='寫回 HouseEtc.detail_dict 與 House 欄位（預設 dry-run）')
    options = parser.parse_args()

    vendor = Vendor.objects.get(name=options.vendor)
    spider = Detail591Spider()
    current = datetime.strptime(options.date_from, '%Y-%m-%d').date()
    end = datetime.strptime(options.date_to, '%Y-%m-%d').date()

    total = ok = failed = written = missing_pack = 0
    while current <= end:
        date_str = current.isoformat()
        pack_path = os.path.join(
            options.raw_dir, options.vendor, date_str + '.tar.zst')
        current += timedelta(days=1)
        if not os.path.exists(pack_path):
            missing_pack += 1
            print('{}: no pack, skip'.format(date_str))
            continue
        print('=== {} ==='.format(pack_path))
        for member, body in iter_pack(pack_path):
            if not member.endswith('.detail.html'):
                continue
            house_id = member.rsplit('.', 2)[0]
            total += 1
            try:
                detail_dict, house_fields = rerun_page(spider, house_id, body)
            except Exception:
                failed += 1
                print('parse error in {}'.format(member))
                traceback.print_exc()
                continue
            ok += 1
            if not options.commit:
                continue
            with transaction.atomic():
                house = House.objects.filter(
                    vendor=vendor, vendor_house_id=house_id).first()
                if house is None:
                    print('{}: not in DB, skip write'.format(house_id))
                    continue
                if detail_dict is not None:
                    HouseEtc.objects.filter(house=house).update(
                        detail_dict=detail_dict)
                if 'author' in house_fields:
                    house_fields['author'], _ = Author.objects.get_or_create(
                        truth=house_fields['author'])
                for attr, value in house_fields.items():
                    setattr(house, attr, value)
                if house_fields:
                    house.save()
                written += 1

    print(json.dumps({
        'detail_pages': total, 'parsed_ok': ok, 'parse_failed': failed,
        'rows_written': written, 'missing_packs': missing_pack,
        'mode': 'commit' if options.commit else 'dry-run',
    }, ensure_ascii=False))
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
