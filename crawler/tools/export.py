import sys
import os
import csv
import argparse
import json
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.paginator import Paginator

sys.path.append('{}/..'.format(
    os.path.dirname(os.path.realpath(__file__))))

from tools.utils import load_django
load_django()

from tools.json_writer import ListWriter
from rental.models import House, HouseEtc
from rental import enums

vendor_stats = {'_total': 0}
page_size = 3000

structured_headers = [
    {'en': 'vendor_house_id', 'zh': '物件編號'},
    {'en': 'vendor', 'zh': '租屋平台', 'field': 'name'},
    {'en': 'vendor_house_url', 'zh': '物件網址'},
    {'en': 'created', 'zh': '物件首次發現時間'},
    {'en': 'updated', 'zh': '物件最後更新時間'},
    {'en': 'top_region', 'zh': '縣市', 'is_enum': enums.TopRegionType},
    {'en': 'sub_region', 'zh': '鄉鎮市區', 'is_enum': enums.SubRegionType},
    {'en': 'deal_status', 'zh': '房屋出租狀態', 'is_enum': enums.DealStatusType},
    {'en': 'deal_time', 'zh': '出租大約時間'},
    {'en': 'n_day_deal', 'zh': '出租所費天數'},
    {'en': 'monthly_price', 'zh': '月租金'},
    {'en': 'deposit_type', 'zh': '押金類型', 'is_enum': enums.DepositType},
    {'en': 'n_month_deposit', 'zh': '押金月數'},
    {'en': 'deposit', 'zh': '押金金額'},
    {'en': 'is_require_management_fee', 'zh': '需要管理費？'},
    {'en': 'monthly_management_fee', 'zh': '月管理費'},
    {'en': 'has_parking', 'zh': '提供車位？'},
    {'en': 'is_require_parking_fee', 'zh': '需要停車費？'},
    {'en': 'monthly_parking_fee', 'zh': '月停車費'},
    {'en': 'per_ping_price', 'zh': '每坪租金（含管理費與停車費）'},
    # {'en': 'detail_dict', 'zh': '建築類型_原始', 'field': 'building_type',
    #     'fn': lambda x: x['side_metas'].get('型態', '')},
    {'en': 'building_type', 'zh': '建築類型', 'is_enum': enums.BuildingType},
    {'en': 'property_type', 'zh': '物件類型', 'is_enum': enums.PropertyType},
    {'en': 'is_rooftop', 'zh': '自報頂加？'},
    # {'en': 'detail_dict', 'zh': '樓層_原始', 'field': 'raw_floor',
    #     'fn': lambda x: x['side_metas'].get('樓層', '')},
    {'en': 'floor', 'zh': '所在樓層'},
    {'en': 'total_floor', 'zh': '建物樓高'},
    {'en': 'dist_to_highest_floor', 'zh': '距頂樓層數'},
    # {'en': 'detail_dict', 'zh': '坪數_原始', 'field': 'ping_raw',
    #     'fn': lambda x: x['side_metas'].get('坪數', '')},
    {'en': 'floor_ping', 'zh': '坪數'},
    {'en': 'n_balcony', 'zh': '陽台數'},
    {'en': 'n_bath_room', 'zh': '衛浴數'},
    {'en': 'n_bed_room', 'zh': '房數'},
    {'en': 'n_living_room', 'zh': '客廳數'},
    {'en': 'apt_feature_code', 'zh': '格局編碼（陽台/衛浴/房/廳）',
        'fn': lambda x: '_{}'.format(x) if x else ''},
    # {'en': 'rough_address', 'zh': '約略住址'},
    # {'en': 'rough_gps', 'zh': '約略經緯度（未實做）'},
    # {'en': 'detail_dict', 'zh': '額外費用_原始', 'field': 'price_includes'},
    {'en': 'additional_fee', 'zh': '額外費用_電費？', 'field': 'eletricity'},
    {'en': 'additional_fee', 'zh': '額外費用_水費？', 'field': 'water'},
    {'en': 'additional_fee', 'zh': '額外費用_瓦斯？', 'field': 'gas'},
    {'en': 'additional_fee', 'zh': '額外費用_網路？', 'field': 'internet'},
    {'en': 'additional_fee', 'zh': '額外費用_第四台？', 'field': 'cable_tv'},
    # {'en': 'detail_dict', 'zh': '生活機能_原始', 'field': 'living_functions',
    #     'fn': lambda x: '/'.join(x['environment'].get('生活機能', []))},
    {'en': 'living_functions', 'field': 'school', 'zh': '附近有_學校？'},
    {'en': 'living_functions', 'field': 'park', 'zh': '附近有_公園？'},
    {'en': 'living_functions', 'field': 'dept_store', 'zh': '附近有_百貨公司？'},
    {'en': 'living_functions', 'field': 'conv_store', 'zh': '附近有_超商？'},
    {'en': 'living_functions', 'field': 'traditional_mkt', 'zh': '附近有_傳統市場？'},
    {'en': 'living_functions', 'field': 'night_mkt', 'zh': '附近有_夜市？'},
    {'en': 'living_functions', 'field': 'hospital', 'zh': '附近有_醫療機構？'},
    # {'en': 'detail_dict', 'zh': '附近交通_原始', 'field': 'transportation',
    #     'fn': lambda x: '/'.join(x['environment'].get('附近交通', []))},
    {'en': 'transportation', 'field': 'subway', 'zh': '附近的捷運站數'},
    {'en': 'transportation', 'field': 'bus', 'zh': '附近的公車站數'},
    {'en': 'transportation', 'field': 'train', 'zh': '附近的火車站數'},
    {'en': 'transportation', 'field': 'hsr', 'zh': '附近的高鐵站數'},
    {'en': 'transportation', 'field': 'public_bike', 'zh': '附近的公共自行車數（實驗中）'},
    # {'en': 'detail_dict', 'zh': '身份限制_原始', 'field': 'tenant_restriction',
    #     'fn': lambda x: x['top_metas'].get('身份要求', '')},
    {'en': 'has_tenant_restriction', 'zh': '有身份限制？'},
    {'en': 'has_gender_restriction', 'zh': '有性別限制？'},
    {'en': 'gender_restriction', 'zh': '性別限制', 'is_enum': enums.GenderType},
    {'en': 'can_cook', 'zh': '可炊？'},
    {'en': 'allow_pet', 'zh': '可寵？'},
    {'en': 'has_perperty_registration', 'zh': '有產權登記？'},
    {'en': 'contact', 'zh': '刊登者類型', 'is_enum': enums.ContactType},
    {'en': 'author', 'zh': '刊登者編碼', 'fn': lambda x: str(x.uuid) if hasattr(x, 'uuid') else None},
    {'en': 'agent_org', 'zh': '仲介資訊'},
]

facilities = [
    '床', '桌子', '椅子', '電視', '熱水器', '冷氣',
    '沙發', '洗衣機', '衣櫃', '冰箱', '網路', '第四台', '天然瓦斯'
]


def gen_facility_header(facility):
    return {
        'en': 'facilities',
        'zh': '提供家具_{}？'.format(facility),
        'field': facility,
        'fn': lambda x: x.get(facility, '')
    }


for facility in facilities:
    structured_headers.append(gen_facility_header(facility))


def print_header(print_enum=True, file_name='rental_house'):
    global structured_headers
    zh_csv = open('{}.csv'.format(file_name), 'w')

    zh_writer = csv.writer(zh_csv)

    zh_csv_header = []

    for header in structured_headers:
        en = header['en']
        if 'field' in header:
            en += '_' + header['field']

        zh_csv_header.append(header['zh'])

        if print_enum and 'is_enum' in header and header['is_enum']:
            zh_csv_header.append(header['zh'] + '_coding')

    zh_writer.writerow(zh_csv_header)

    return zh_writer

def prepare_houses(from_date, to_date):
    global page_size
    houses = House.objects.filter(
        additional_fee__isnull=False,
        created__lte=to_date,
        crawled_at__gte=from_date
    ).order_by(
        '-id'
    )
    paginator = Paginator(houses, page_size)
    return paginator

def normalize_val(val, header, use_tf):
    json_val = val
    if 'fn' in header:
        val = header['fn'](val)
        json_val = val
    elif val is not None and 'field' in header:
        if hasattr(val, header['field']):
            val = getattr(val, header['field'])
            json_val = val
        elif 'field' in header and header['field'] in val:
            val = val[header['field']]
            json_val = val
        else:
            val = ''
            json_val = ''

    if type(val) is datetime:
        val = timezone.localtime(val).strftime('%Y-%m-%d %H:%M:%S %Z')
        json_val = val
    if val is None or val is '':
        val = '-'
        json_val = None
    elif val is True:
        val = 'T' if use_tf else 1
        json_val = True
    elif val is False:
        val = 'F' if use_tf else 0
        json_val = False

    return val, json_val

def print_body(writer, houses, print_enum=True, use_tf=False, listWriter=None):
    global structured_headers
    global vendor_stats
    count = 0

    for house in houses:

        if house.vendor.name not in vendor_stats:
            vendor_stats[house.vendor.name] = 0

        vendor_stats[house.vendor.name] += 1
        vendor_stats['_total'] += 1

        row = []
        obj = {}

        for header in structured_headers:
            header_name = header['en']
            if not hasattr(house, header_name):
                row.append('-')
                obj[header['en']] = None
            else:
                val, json_val = normalize_val(getattr(house, header_name), header, use_tf)

                if print_enum:
                    row.append(val)
                    obj[header_name] = json_val
                    if 'is_enum' in header and header['is_enum']:
                        if val != '-':
                            row.append(header['is_enum'](val).name)
                            obj[header_name] = header['is_enum'](val).name
                        else:
                            row.append(val)
                            obj[header_name] = json_val
                else:
                    row.append(val)
                    obj[header_name] = json_val

        writer.writerow(row)

        if list_writer:
            try:
                filename = enums.TopRegionType(house.top_region).name
            except:
                filename = 'default'

            list_writer.write(
                filename, 
                obj
            )

        count += 1

    return count


def parse_date(input):
    try: 
        return timezone.make_aware(datetime.strptime(input, '%Y%m%d'))
    except ValueError:
        raise argparse.ArgumentTypeError('Invalid date string: {}'.format(input))

arg_parser = argparse.ArgumentParser(description='Export house to csv')
arg_parser.add_argument(
    '-e',
    '--enum',
    default=False,
    const=True,
    nargs='?',
    help='print enumeration or not')

arg_parser.add_argument(
    '-f',
    '--from',
    dest='from_date',
    default=None,
    type=parse_date,
    help='from date, format: YYYYMMDD, default today'
)

arg_parser.add_argument(
    '-t',
    '--to',
    dest='to_date',
    default=None,
    type=parse_date,
    help='to date, format: YYYYMMDD, default today'
)

arg_parser.add_argument(
    '-o',
    '--outfile',
    default='rental_house',
    help='output file name, without postfix(.csv)'
)

arg_parser.add_argument(
    '-j',
    '--json',
    default=False,
    const=True,
    nargs='?',
    help='export json or not, each top region will be put in seperated files'
)

arg_parser.add_argument(
    '-01',
    '--01-instead-of-truefalse',
    dest='use_01',
    default=False,
    const=True,
    nargs='?',
    help='use T/F to express boolean value in csv, instead of 1/0'
)

if __name__ == '__main__':

    args = arg_parser.parse_args()
    
    print_enum = args.enum is not False
    want_json = args.json is not False
    use_tf = args.use_01 is not True
    from_date = args.from_date
    to_date = args.to_date
    
    if from_date is None:
        from_date = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if to_date is None:
        to_date = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if from_date > to_date:
        from_date, to_date = to_date, from_date

    to_date += timedelta(days=1)

    writer = print_header(print_enum, args.outfile)

    list_writer = None

    if want_json:
        list_writer = ListWriter(args.outfile)

    print('===== Export all houses from {} to {} ====='.format(from_date, to_date))
    paginator = prepare_houses(from_date, to_date)
    total = paginator.count
    current_done = 0
    for page_num in paginator.page_range:
        houses = paginator.page(page_num)
        n_raws = print_body(writer, houses, print_enum, use_tf, list_writer)
        current_done += n_raws
        print('[{}] we have {}/{} rows'.format(datetime.now(), current_done, total))

    if want_json:
        list_writer.closeAll()

    with open('{}.json'.format(args.outfile), 'w') as file:
        json.dump(vendor_stats, file, ensure_ascii=False)

    print('===== Export done =====\nData: {}.csv\nStatistics: {}.json\n'.format(args.outfile, args.outfile))
