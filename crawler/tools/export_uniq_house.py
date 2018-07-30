import sys
import os
import csv
import argparse
import json
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.paginator import Paginator
from django.contrib.postgres.fields.jsonb import KeyTextTransform, KeyTransform
from django.db import models
from django.db.models.functions import Cast
from django.db.models import Count, Max, Min, Avg, TextField

sys.path.append('{}/..'.format(
    os.path.dirname(os.path.realpath(__file__))))

from tools.utils import load_django
from tools.json_writer import ListWriter
load_django()

from rental.models import House, HouseEtc, Vendor
from rental import enums

vendor_stats = {'_total': 0}
page_size = 3000

vendors = {}
for vendor in Vendor.objects.all():
    vendors[vendor.id] = vendor.name

def lookup_vendor(vendor_id):
    global vendors
    return vendors[vendor_id]

structured_headers = [
    {'en': 'n_duplicate', 'zh': '重複物件數', 'annotate': Count('id')},
    {'en': 'max_house_id', 'zh': '最大物件編號', 'annotate': Max('vendor_house_id')},
    {'en': 'min_house_id', 'zh': '最小物件編號', 'annotate': Min('vendor_house_id')},
    {'en': 'max_created', 'zh': '最大物件首次發現時間', 'annotate': Max('created')},
    {'en': 'min_created', 'zh': '最小物件首次發現時間', 'annotate': Min('created')},

    {'en': 'vendor', 'zh': '租屋平台', 'fn': lookup_vendor},
    {'en': 'top_region', 'zh': '縣市', 'is_enum': enums.TopRegionType},
    {'en': 'sub_region', 'zh': '鄉鎮市區', 'is_enum': enums.SubRegionType},
    {'en': 'has_dealt', 'zh': '房屋曾出租過', 'is_enum': enums.DealStatusType, 'annotate': Max('deal_status')},
    {'en': 'max_deal_time', 'zh': '最後出租時間', 'annotate': Max('deal_time')},
    {'en': 'max_n_day_deal', 'zh': '最大出租所費天數', 'annotate': Max('n_day_deal')},
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
    {'en': 'building_type', 'zh': '建築類型', 'is_enum': enums.BuildingType},
    {'en': 'property_type', 'zh': '物件類型', 'is_enum': enums.PropertyType},
    {'en': 'is_rooftop', 'zh': '自報頂加？'},
    {'en': 'floor', 'zh': '所在樓層'},
    {'en': 'total_floor', 'zh': '建物樓高'},
    {'en': 'dist_to_highest_floor', 'zh': '距頂樓層數'},
    {'en': 'floor_ping', 'zh': '坪數'},
    {'en': 'n_balcony', 'zh': '陽台數'},
    {'en': 'n_bath_room', 'zh': '衛浴數'},
    {'en': 'n_bed_room', 'zh': '房數'},
    {'en': 'n_living_room', 'zh': '客廳數'},
    {'en': 'apt_feature_code', 'zh': '格局編碼（陽台/衛浴/房/廳）',
        'fn': lambda x: '_{}'.format(x) if x else ''},
    {'en': 'additional_fee_eletricity', 'zh': '額外費用_電費？', 'annotate': KeyTextTransform('eletricity','additional_fee')},
    {'en': 'additional_fee_water', 'zh': '額外費用_水費？', 'annotate': KeyTextTransform('water','additional_fee')},
    {'en': 'additional_fee_gas', 'zh': '額外費用_瓦斯？', 'annotate': KeyTextTransform('gas','additional_fee')},
    {'en': 'additional_fee_internet', 'zh': '額外費用_網路？', 'annotate': KeyTextTransform('internet','additional_fee')},
    {'en': 'additional_fee_cable_tv', 'zh': '額外費用_第四台？', 'annotate': KeyTextTransform('cable_tv','additional_fee')},
    {'en': 'living_functions_school', 'zh': '附近有_學校？', 'annotate': KeyTextTransform('school','living_functions')},
    {'en': 'living_functions_park', 'zh': '附近有_公園？', 'annotate': KeyTextTransform('park','living_functions')},
    {'en': 'living_functions_dept_store', 'zh': '附近有_百貨公司？', 'annotate': KeyTextTransform('dept_store','living_functions')},
    {'en': 'living_functions_conv_store', 'zh': '附近有_超商？', 'annotate': KeyTextTransform('conv_store','living_functions')},
    {'en': 'living_functions_traditional_mkt', 'zh': '附近有_傳統市場？', 'annotate': KeyTextTransform('traditional_mkt','living_functions')},
    {'en': 'living_functions_night_mkt', 'zh': '附近有_夜市？', 'annotate': KeyTextTransform('night_mkt','living_functions')},
    {'en': 'living_functions_hospital', 'zh': '附近有_醫療機構？', 'annotate': KeyTextTransform('hospital','living_functions')},
    {'en': 'transportation_subway', 'zh': '附近的捷運站數', 'annotate': KeyTextTransform('subway','transportation')},
    {'en': 'transportation_bus', 'zh': '附近的公車站數', 'annotate': KeyTextTransform('bus','transportation')},
    {'en': 'transportation_train', 'zh': '附近的火車站數', 'annotate': KeyTextTransform('train','transportation')},
    {'en': 'transportation_hsr', 'zh': '附近的高鐵站數', 'annotate': KeyTextTransform('hsr','transportation')},
    {'en': 'transportation_public_bike', 'zh': '附近的公共自行車數（實驗中）', 'annotate': KeyTextTransform('public_bike','transportation')},
    # {
    #     'en': 'tenant_restriction',
    #     'zh': '身份限制',
    #     'annotate': KeyTextTransform('身份要求', KeyTransform('top_metas', 'etc__detail_dict')),
    #     'fn': lambda x: [] if x is None else json.loads(x),
    #     'expand_header': [
    #         {'en': 'student', 'zh': '學生？', 'fn': lambda field_value: '學生' in field_value},
    #         {'en': 'office_worker', 'zh': '上班族？', 'fn': lambda field_value: '上班族' in field_value},
    #         {'en': 'family', 'zh': '家庭？', 'fn': lambda field_value: '家庭' in field_value}
    #     ]
    # },
    {'en': 'has_tenant_restriction', 'zh': '有身份限制？'},
    {'en': 'has_gender_restriction', 'zh': '有性別限制？'},
    {'en': 'gender_restriction', 'zh': '性別限制', 'is_enum': enums.GenderType},
    {'en': 'can_cook', 'zh': '可炊？'},
    {'en': 'allow_pet', 'zh': '可寵？'},
    {'en': 'has_perperty_registration', 'zh': '有產權登記？'},
    {'en': 'contact', 'zh': '刊登者類型', 'is_enum': enums.ContactType},
    {'en': 'max_author_id', 'zh': '最大刊登者編碼', 'annotate': Max(Cast('author_id', TextField()))},
    {'en': 'agent_org', 'zh': '仲介資訊'},
]

facilities = [
    '床', '桌子', '椅子', '電視', '熱水器', '冷氣',
    '沙發', '洗衣機', '衣櫃', '冰箱', '網路', '第四台', '天然瓦斯'
]

def gen_facility_header(facility):
    return {
        'en': 'facilities_{}'.format(facility),
        'zh': '提供家具_{}？'.format(facility),
        'annotate': KeyTextTransform(facility,'facilities'),
    }


for facility in facilities:
    structured_headers.append(gen_facility_header(facility))


def print_header(print_enum=True, file_name='rental_house'):
    global structured_headers
    zh_csv = open('{}.csv'.format(file_name), 'w')

    zh_writer = csv.writer(zh_csv)

    zh_csv_header = []

    for header in structured_headers:

        if print_enum and 'is_enum' in header and header['is_enum']:
            zh_csv_header.append(header['zh'])
            zh_csv_header.append(header['zh'] + '_coding')
        elif 'expand_header' in header:
            for more_header in header['expand_header']:
                zh_csv_header.append('{}_{}'.format(header['zh'], more_header['zh']))
        else:
            zh_csv_header.append(header['zh'])

    # en_writer.writerow(en_csv_header)
    zh_writer.writerow(zh_csv_header)

    return zh_writer

def prepare_houses(from_date, to_date, only_liudu = False):
    global page_size
    search_values = []
    search_annotates = {}

    optional_filter = {}

    if only_liudu:
        optional_filter['top_region__in'] = [
            enums.TopRegionType.台北市,
            enums.TopRegionType.新北市,
            enums.TopRegionType.桃園市,
            enums.TopRegionType.台中市,
            enums.TopRegionType.台南市,
            enums.TopRegionType.高雄市,
        ]

    for header in structured_headers:
        if 'annotate' in header:
            search_annotates[header['en']] = header['annotate']
        else:
            search_values.append(header['en'])

    houses = House.objects.values(
        *search_values
    ).annotate(
        **search_annotates
    ).filter(
        additional_fee__isnull=False,
        building_type__in=[
            enums.BuildingType.公寓,
            enums.BuildingType.透天,
            enums.BuildingType.電梯大樓
        ],
        property_type__in=[
            enums.PropertyType.整層住家,
            enums.PropertyType.獨立套房,
            enums.PropertyType.分租套房,
            enums.PropertyType.雅房
        ],
        **optional_filter,
        total_floor__lt=90,
        floor__lt=90,
        floor__lte=(models.F('total_floor')+2),
        floor_ping__lt=500,
        per_ping_price__lte=15000,
        created__lte=to_date,
        crawled_at__gte=from_date,
    ).order_by(
        'max_house_id'
    )

    # print(houses.query)

    paginator = Paginator(houses, page_size)
    return paginator

def normalize_val(val, header, use_tf):
    json_val = val

    if 'fn' in header:
        val = header['fn'](val)
        json_val = val

    if type(val) is datetime:
        val = timezone.localtime(val).strftime('%Y-%m-%d %H:%M:%S %Z')
        json_val = val
    elif val is '' or val is None:
        val = '-'
        json_val = None
    elif val is True or val == 'true':
        val = 'T' if use_tf else 1
        json_val = True
    elif val is False or val == 'false':
        val = 'F' if use_tf else 0
        json_val = False

    return val, json_val

def print_body(writer, houses, print_enum=True, use_tf=False, listWriter=None):
    global structured_headers
    global vendor_stats
    count = 0

    for house in houses:

        vendor_name = lookup_vendor(house['vendor'])
        if vendor_name not in vendor_stats:
            vendor_stats[vendor_name] = 0

        vendor_stats[vendor_name] += 1
        vendor_stats['_total'] += 1

        row = []
        obj = {}
        for header in structured_headers:
            field = header['en']
            if field not in house:
                obj[field] = None
                row.append('-')
                obj[header['en']] = None
            else:
                val, json_val = normalize_val(house[field], header, use_tf)

                if print_enum:
                    obj[field] = json_val
                    row.append(val)
                    if 'is_enum' in header and header['is_enum']:
                        if val != '-':
                            obj[field] = header['is_enum'](val).name
                            row.append(header['is_enum'](val).name)
                        else:
                            obj[field] = json_val
                            row.append(val)
                elif 'expand_header' in header:
                    for more_header in header['expand_header']:
                        more_val, more_json_val = normalize_val(val, more_header, use_tf)
                        row.append(more_val)
                        obj['{}_{}'.format(field, more_header['en'])] = more_json_val
                else:
                    obj[field] = json_val
                    row.append(val)

        writer.writerow(row)

        if list_writer:
            filename = ''
            if 'top_region' in house:
                filename = enums.TopRegionType(house['top_region']).name

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
    '-b6',
    '--liudu',
    default=False,
    const=True,
    nargs='?',
    help='only export 六都'
)

arg_parser.add_argument(
    '-tf',
    '--truefalse-instead-of-10',
    dest='use_tf',
    default=False,
    const=True,
    nargs='?',
    help='use T/F to express boolean value in csv, instead of 1/0'
)

if __name__ == '__main__':

    args = arg_parser.parse_args()
    
    print_enum = args.enum is not False
    want_json = args.json is not False
    use_tf = args.use_tf is not False
    liudu = args.liudu is not False
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
    paginator = prepare_houses(from_date, to_date, liudu)
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
