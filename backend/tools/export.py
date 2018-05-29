import sys
import os
import csv
import argparse
from datetime import datetime, timedelta
# import logging
sys.path.append('{}/../..'.format(
    os.path.dirname(os.path.realpath(__file__))))

from backend.db.models import House, HouseEtc, tw_tz
from backend.db import enums

# logging.basicConfig(
#     format='%(levelname)s: %(message)s',
#     level=logging.DEBUG
# )


structured_headers = [
    {'en': 'vendor_house_id', 'zh': '物件編號'},
    {'en': 'vendor', 'zh': '租屋平台', 'field': 'name'},
    {'en': 'vendor_house_url', 'zh': '物件網址'},
    {'en': 'created', 'zh': '物件首次發現時間'},
    {'en': 'updated', 'zh': '物件最後更新時間'},
    {'en': 'top_region', 'zh': '縣市', 'is_enum': enums.TopRegionField()},
    {'en': 'sub_region', 'zh': '鄉鎮市區', 'is_enum': enums.SubRegionField()},
    {'en': 'deal_status', 'zh': '房屋出租狀態', 'is_enum': enums.DealStatusField()},
    {'en': 'deal_time', 'zh': '出租大約時間'},
    {'en': 'n_day_deal', 'zh': '出租所費天數'},
    {'en': 'monthly_price', 'zh': '月租金'},
    {'en': 'deposit_type', 'zh': '押金類型', 'is_enum': enums.DepositTypeField()},
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
    {'en': 'building_type', 'zh': '建築類型', 'is_enum': enums.BuildingTypeField()},
    {'en': 'property_type', 'zh': '物件類型', 'is_enum': enums.PropertyTypeField()},
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
    {'en': 'gender_restriction', 'zh': '性別限制', 'is_enum': enums.GenderTypeField()},
    {'en': 'can_cook', 'zh': '可炊？'},
    {'en': 'allow_pet', 'zh': '可寵？'},
    {'en': 'has_perperty_registration', 'zh': '有產權登記？'},
    {'en': 'contact', 'zh': '刊登者類型', 'is_enum': enums.ContactTypeField()},
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
    # looks like no one need en version XD
    # en_csv = open('rental_house.en.csv', 'w')
    zh_csv = open('{}.csv'.format(file_name), 'w')

    # en_writer = csv.writer(en_csv)
    zh_writer = csv.writer(zh_csv)

    # en_csv_header = []
    zh_csv_header = []

    for header in structured_headers:
        en = header['en']
        if 'field' in header:
            en += '_' + header['field']

        # en_csv_header.append(en)
        zh_csv_header.append(header['zh'])

        if print_enum and 'is_enum' in header and header['is_enum']:
            # en_csv_header.append(en + '_coding')
            zh_csv_header.append(header['zh'] + '_coding')

    # en_writer.writerow(en_csv_header)
    zh_writer.writerow(zh_csv_header)

    return zh_writer


def print_body(writer, from_date, to_date, page=1, print_enum=True):
    global structured_headers
    houses = House.select(
        House.vendor_house_id,
        House.vendor,
        House.created,
        House.updated,
        House.vendor_house_url,
        House.top_region,
        House.sub_region,
        House.deal_status,
        House.deal_time,
        House.n_day_deal,
        House.monthly_price,
        House.deposit_type,
        House.n_month_deposit,
        House.deposit,
        House.is_require_management_fee,
        House.monthly_management_fee,
        House.has_parking,
        House.is_require_parking_fee,
        House.monthly_parking_fee,
        House.per_ping_price,
        House.building_type,
        House.property_type,
        House.is_rooftop,
        House.floor,
        House.total_floor,
        House.dist_to_highest_floor,
        House.floor_ping,
        House.n_living_room,
        House.n_bed_room,
        House.n_bath_room,
        House.n_balcony,
        House.apt_feature_code,
        House.rough_address,
        House.rough_gps,
        House.additional_fee,
        House.living_functions,
        House.transportation,
        House.has_tenant_restriction,
        House.has_gender_restriction,
        House.gender_restriction,
        House.can_cook,
        House.allow_pet,
        House.has_perperty_registration,
        House.contact,
        House.agent_org,
        House.imgs,
        House.facilities,
    #     HouseEtc.detail_dict,
    # ).join(
    #     HouseEtc
    ).where(
        # House.building_type != enums.BuildingTypeField.enums.倉庫,
        # House.building_type != getattr(enums.BuildingTypeField.enums, '店面（店鋪）'),
        # House.building_type != enums.BuildingTypeField.enums.辦公商業大樓,
        # House.property_type != enums.PropertyTypeField.enums.車位,
        # House.property_type != enums.PropertyTypeField.enums.倉庫,
        # House.property_type != enums.PropertyTypeField.enums.場地,
        House.additional_fee != None,
        House.created <= to_date,
        House.updated >= from_date
    ).order_by(
        House.id.desc()
    ).paginate(
        page, 5000
    ).objects()

    count = houses.count()
    if count == 0:
        return 0

    for house in houses:
        row = []
        for header in structured_headers:
            if not hasattr(house, header['en']):
                row.append('-')
            else:
                val = getattr(house, header['en'])
                if 'fn' in header:
                    val = header['fn'](val)
                elif 'field' in header:
                    if hasattr(val, header['field']):
                        val = getattr(val, header['field'])
                    elif 'field' in header and header['field'] in val:
                        val = val[header['field']]
                    else:
                        val = ''

                if type(val) is datetime:
                    val = val.replace(tzinfo=tw_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                if val is None or val is '':
                    val = '-'
                elif val is True:
                    val = 1
                elif val is False:
                    val = 0

                if print_enum:
                    row.append(val)
                    if 'is_enum' in header and header['is_enum']:
                        row.append(header['is_enum'].db_value(val))
                else:
                    if 'is_enum' in header and header['is_enum']:
                        row.append(header['is_enum'].db_value(val))
                    else:
                        row.append(val)

        writer.writerow(row)

    return count


def parse_date(input):
    try: 
        return datetime.strptime(input, '%Y%m%d')
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

if __name__ == '__main__':

    args = arg_parser.parse_args()
    page = 1
    total = 0
    print_enum = args.enum is not False
    from_date = args.from_date
    to_date = args.to_date
    if from_date is None:
        from_date = datetime.now(tz=tw_tz).replace(hour=0, minute=0, second=0, microsecond=0)

    if to_date is None:
        to_date = datetime.now(tz=tw_tz).replace(hour=0, minute=0, second=0, microsecond=0)

    if from_date > to_date:
        from_date, to_date = to_date, from_date

    to_date += timedelta(days=1)

    writer = print_header(print_enum, args.outfile)
    print('===== Export all houses from {} to {} ====='.format(from_date, to_date))
    while True:
        ret = print_body(writer, from_date, to_date, page, print_enum)
        total += ret
        page += 1
        if not ret:
            break
        print('[{}] we have {} rows'.format(datetime.now(), total))
