import sys
import os
import csv
from datetime import datetime
# import logging
sys.path.append('{}/../..'.format(
    os.path.dirname(os.path.realpath(__file__))))

from backend.db.models import House, HouseEtc
from backend.db import enums

# logging.basicConfig(
#     format='%(levelname)s: %(message)s',
#     level=logging.DEBUG
# )


structured_headers = [
    {'en': 'vendor_house_id', 'zh': '物件編號'},
    {'en': 'vendor', 'zh': '租屋平台', 'field': 'name'},
    {'en': 'vendor_house_url', 'zh': '物件網址'},
    {'en': 'created', 'zh': '物件首次發現'},
    {'en': 'top_region', 'zh': '縣市'},
    {'en': 'sub_region', 'zh': '鄉鎮市區'},
    {'en': 'deal_status', 'zh': '房屋出租狀態', 'is_enum': enums.DealStatusField()},
    {'en': 'deal_time', 'zh': '出租大約時間'},
    {'en': 'n_day_deal', 'zh': '出租所費天數'},
    {'en': 'detail_dict', 'zh': '押金_原始', 'field': 'deposit',
        'fn': lambda x: x['top_metas'].get('押金', '')},
    {'en': 'monthly_price', 'zh': '月租金'},
    {'en': 'deposit_type', 'zh': '押金類型', 'is_enum': enums.DepositTypeField()},
    {'en': 'n_month_deposit', 'zh': '押金月數'},
    {'en': 'deposit', 'zh': '押金金額'},
    {'en': 'is_require_management_fee', 'zh': '需要管理費？'},
    {'en': 'monthly_management_fee', 'zh': '月管理費'},
    {'en': 'detail_dict', 'zh': '車位_原始', 'field': 'parking',
        'fn': lambda x: x['top_metas'].get('車 位', '')},
    {'en': 'detail_dict', 'zh': '車位類型', 'field': 'parking_type',
        'fn': lambda x: x['top_metas'].get('車 位', '').split('，')[0]},
    {'en': 'has_parking', 'zh': '提供車位？'},
    {'en': 'is_require_parking_fee', 'zh': '需要停車費？'},
    {'en': 'monthly_parking_fee', 'zh': '月停車費'},
    {'en': 'per_ping_price', 'zh': '每坪租金（含管理費與停車費）'},
    {'en': 'detail_dict', 'zh': '建築類型_原始', 'field': 'building_type',
        'fn': lambda x: x['side_metas'].get('型態', '')},
    {'en': 'building_type', 'zh': '建築類型', 'is_enum': enums.BuildingTypeField()},
    {'en': 'property_type', 'zh': '物件類型', 'is_enum': enums.PropertyTypeField()},
    {'en': 'is_rooftop', 'zh': '自報頂加？'},
    {'en': 'detail_dict', 'zh': '樓層_原始', 'field': 'raw_floor',
        'fn': lambda x: x['side_metas'].get('樓層', '')},
    {'en': 'floor', 'zh': '所在樓層'},
    {'en': 'total_floor', 'zh': '建物樓層'},
    {'en': 'detail_dict', 'zh': '坪數_原始', 'field': 'ping_raw',
        'fn': lambda x: x['side_metas'].get('坪數', '')},
    {'en': 'floor_ping', 'zh': '坪數'},
    {'en': 'n_balcony', 'zh': '陽台數'},
    {'en': 'n_bath_room', 'zh': '衛浴數'},
    {'en': 'n_bed_room', 'zh': '房數'},
    {'en': 'n_living_room', 'zh': '客廳數'},
    {'en': 'apt_feature_code', 'zh': '格局編碼（陽台/衛浴/房/廳）',
        'fn': lambda x: '_{}'.format(x) if x else ''},
    {'en': 'rough_address', 'zh': '約略住址'},
    {'en': 'rough_gps', 'zh': '約略經緯度（未實做）'},
    {'en': 'detail_dict', 'zh': '額外費用_原始', 'field': 'price_includes'},
    {'en': 'detail_dict', 'zh': '額外費用_管理費？', 'field': 'mamagement',
        'fn': lambda dd: '含管理費' not in dd['price_includes']},
    {'en': 'detail_dict', 'zh': '額外費用_清潔費？', 'field': 'house_keeping',
        'fn': lambda dd: '清潔費' not in dd['price_includes'] and '含清潔費' not in dd['price_includes']},
    {'en': 'additional_fee', 'zh': '額外費用_電費？', 'field': 'eletricity'},
    {'en': 'additional_fee', 'zh': '額外費用_水費？', 'field': 'water'},
    {'en': 'additional_fee', 'zh': '額外費用_瓦斯？', 'field': 'gas'},
    {'en': 'additional_fee', 'zh': '額外費用_網路？', 'field': 'internet'},
    {'en': 'additional_fee', 'zh': '額外費用_第四台？', 'field': 'cable_tv'},
    {'en': 'detail_dict', 'zh': '生活機能_原始', 'field': 'living_functions',
        'fn': lambda x: '/'.join(x['environment'].get('生活機能', []))},
    {'en': 'living_functions', 'field': 'school', 'zh': '附近有_學校？'},
    {'en': 'living_functions', 'field': 'park', 'zh': '附近有_公園？'},
    {'en': 'living_functions', 'field': 'dept_store', 'zh': '附近有_百貨公司？'},
    {'en': 'living_functions', 'field': 'conv_store', 'zh': '附近有_超商？'},
    {'en': 'living_functions', 'field': 'traditional_mkt', 'zh': '附近有_傳統市場？'},
    {'en': 'living_functions', 'field': 'night_mkt', 'zh': '附近有_夜市？'},
    {'en': 'living_functions', 'field': 'hospital', 'zh': '附近有_醫療機構？'},
    {'en': 'detail_dict', 'zh': '附近交通_原始', 'field': 'transportation',
        'fn': lambda x: '/'.join(x['environment'].get('附近交通', []))},
    {'en': 'transportation', 'field': 'subway', 'zh': '附近有捷運站？',
        'fn': lambda x: '' if 'subway' not in x else x['subway'] > 0},
    {'en': 'transportation', 'field': 'bus', 'zh': '附近有公車站？',
        'fn': lambda x: '' if 'bus' not in x else x['bus'] > 0},
    {'en': 'transportation', 'field': 'train', 'zh': '附近有火車站？',
        'fn': lambda x: '' if 'train' not in x else x['train'] > 0},
    {'en': 'transportation', 'field': 'public_bike', 'zh': '附近有公共自行車數？',
        'fn': lambda x: '' if 'public_bike' not in x else x['public_bike'] > 0},
    {'en': 'detail_dict', 'zh': '身份限制_原始', 'field': 'tenant_restriction',
        'fn': lambda x: x['top_metas'].get('身份要求', '')},
    {'en': 'detail_dict', 'zh': '身份限制_學生？', 'field': 'tenant_restriction_student',
        'fn': lambda x: '' if x['top_metas'].get('身份要求',None) == None else '學生' in x['top_metas'].get('身份要求', [])},
    {'en': 'detail_dict', 'zh': '身份限制_上班族？', 'field': 'tenant_restriction_labor',
        'fn': lambda x: '' if x['top_metas'].get('身份要求',None) == None else '上班族' in x['top_metas'].get('身份要求', [])},
    {'en': 'detail_dict', 'zh': '身份限制_家庭？', 'field': 'tenant_restriction_family',
        'fn': lambda x: '' if x['top_metas'].get('身份要求',None) == None else '家庭' in x['top_metas'].get('身份要求', [])},
    {'en': 'detail_dict', 'zh': '身份限制_三項皆有？', 'field': 'tenant_restriction_family',
        'fn': lambda x: '' if x['top_metas'].get('身份要求',None) == None else len(x['top_metas'].get('身份要求', [])) == 3},
    # {'en': 'has_tenant_restriction', 'zh': '有身份限制？'},
    {'en': 'detail_dict', 'zh': '性別限制_原始', 'field': 'gender_restriction',
        'fn': lambda x: x['top_metas'].get('性別要求', '')},
    {'en': 'has_gender_restriction', 'zh': '有性別限制？'},
    {'en': 'gender_restriction', 'zh': '性別限制', 'is_enum': enums.GenderTypeField()},
    {'en': 'detail_dict', 'zh': '可炊_原始', 'field': 'cook',
        'fn': lambda x: x['top_metas'].get('開伙', '')},
    {'en': 'can_cook', 'zh': '可炊？'},
    {'en': 'detail_dict', 'zh': '可寵_原始', 'field': 'pet',
        'fn': lambda x: x['top_metas'].get('養寵物', '')},
    {'en': 'allow_pet', 'zh': '可寵？'},
    {'en': 'detail_dict', 'zh': '產權登記_原始', 'field': 'tenant_restriction',
        'fn': lambda x: x['top_metas'].get('產權登記', '')},
    {'en': 'has_perperty_registration', 'zh': '有產權登記？'},
    {'en': 'contact', 'zh': '刊登者類型', 'is_enum': enums.ContactTypeField()},
    {'en': 'agent_org', 'zh': '仲介資訊'},
    {'en': 'detail_dict', 'zh': '標題', 'field': 'title',
        'fn': lambda x: x.get('title', '')},
    {'en': 'detail_dict', 'zh': '說明', 'field': 'desp',
        'fn': lambda x: ' '.join(x.get('desp', []))},
    {'en': 'imgs', 'zh': '圖片們'},
    {'en': 'detail_dict', 'zh': '最短租期_原始', 'field': 'min_rent_period_raw',
        'fn': lambda x: x['top_metas'].get('最短租期', '')},
    {'en': 'detail_dict', 'zh': '隔間材料', 'field': 'material_type',
        'fn': lambda x: x['top_metas'].get('隔間材料', '')},
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

misc_header = [
    {'en': 'facilities', 'zh': '提供家具', 'field': 'include'},
    {'en': 'facilities', 'zh': '沒提供家具', 'field': 'without'},
]


def print_header():
    global structured_headers
    global misc_header
    # en_csv = open('rental_house.en.csv', 'w')
    zh_csv = open('rental_house.zh.csv', 'w')

    # en_writer = csv.writer(en_csv)
    zh_writer = csv.writer(zh_csv)

    # en_csv_header = []
    zh_csv_header = []

    for header in structured_headers + misc_header:
        en = header['en']
        if 'field' in header:
            en += '_' + header['field']

        # en_csv_header.append(en)
        zh_csv_header.append(header['zh'])

        if 'is_enum' in header and header['is_enum']:
            # en_csv_header.append(en + '_coding')
            zh_csv_header.append(header['zh'] + '_coding')

    # en_writer.writerow(en_csv_header)
    zh_writer.writerow(zh_csv_header)

    return zh_writer


def print_body(writer, page=1):
    global structured_headers
    global misc_header
    houses = House.select(
        House.vendor_house_id,
        House.vendor,
        House.created,
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
        HouseEtc.detail_dict,
        HouseEtc.list_raw
    ).join(
        HouseEtc
    ).where(
        # House.building_type != enums.BuildingTypeField.enums.倉庫,
        # House.building_type != getattr(enums.BuildingTypeField.enums, '店面（店鋪）'),
        # House.building_type != enums.BuildingTypeField.enums.辦公商業大樓,
        # House.property_type != enums.PropertyTypeField.enums.車位,
        # House.property_type != enums.PropertyTypeField.enums.倉庫,
        # House.property_type != enums.PropertyTypeField.enums.場地,
        House.additional_fee != None
    ).order_by(
        House.id.desc()
    ).paginate(
        page, 1000
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

                if val is None or val is '':
                    val = '-'
                elif val is True:
                    val = 1
                elif val is False:
                    val = 2
                row.append(val)

                if 'is_enum' in header and header['is_enum']:
                    row.append(header['is_enum'].db_value(val))

        facilities = house.facilities
        without_facilities = []
        with_facilities = []
        for name in facilities:
            if facilities[name]:
                with_facilities.append(name)
            else:
                without_facilities.append(name)

        row.append(with_facilities)
        row.append(without_facilities)

        writer.writerow(row)

    return count


if __name__ == '__main__':
    page = 1
    total = 0
    writer = print_header()
    while True:
        ret = print_body(writer, page)
        total += ret
        print('[{}] we have {} rows'.format(datetime.now(), total))
        page += 1
        if not ret:
            break
