import json
import re
import logging
from functools import reduce
from urllib.parse import urlparse, parse_qs
from decimal import Decimal
from functools import partial
from scrapy_twrh.spiders import enums
from scrapy_twrh.spiders.util import clean_number
from scrapy_twrh.items import RawHouseItem, GenericHouseItem
from .request_generator import RequestGenerator
from .util import parse_price, css, from_zh_number
from .detail_raw_parser import get_detail_raw_attrs


class ShortBreadcrumbError(ValueError):
    '''
    The served page has fewer than two breadcrumb levels, so top/sub region
    cannot be told. Observed as a transient 591 server-side variant
    (2026-08-30, six pages, all normal on retry).

    Raised instead of storing a house without regions, so that the persist
    queue keeps the request and a later batch retries it. A page that stays
    short across retries surfaces as a lasting failure instead of quietly
    losing fields.
    '''

# copy from stackoverflow XD
# https://stackoverflow.com/questions/25833613/safe-method-to-get-value-of-nested-dictionary
def get(dictionary, keys, default=None):
    return reduce(lambda d, key: d.get(key, default) if isinstance(d, dict) else default, keys.split("."), dictionary)

def list_to_dict (list, name_field = 'name', value_field = 'value'):
    ret = {}
    for item in list:
        ret[item[name_field]] = item[value_field]
    return ret

def dict_from_tuple(keys, values):
    min_length = min(len(keys), len(values))
    ret = {}

    for i in range(min_length):
        ret[keys[i]] = values[i]

    return ret

def split_string_to_dict(string, seperator):
    tokens = string.split(seperator)
    if len(tokens) >= 2:
        return {tokens[0]: tokens[1]}

    return None

# how 591 writes a unit built on top of the highest floor, old wording first
ROOFTOP_FLOORS = ('頂樓加蓋', '頂層加蓋')

def misc_of(detail_dict, *labels):
    '''
    Value of the first 591 label which is present, as a list.

    591 renames these labels once in a while - 車位費 became 車位租金 in the
    2026 template - so every caller passes the labels it knows about, newest
    first. The list is always a list, both parsers store one entry per value.
    '''
    misc = get(detail_dict, 'misc', default={}) or {}
    for label in labels:
        if label in misc:
            value = misc[label]
            return value if isinstance(value, list) else [value]

    return []

def misc_text_of(detail_dict, *labels):
    '''
    Same as misc_of, joined back into the text 591 shows, say '2,035元/月'
    '''
    return '、'.join(misc_of(detail_dict, *labels))

class DetailMixin(RequestGenerator):
    apt_features = {
        'n_living_room': '廳',
        'n_bed_room': '房',
        'n_bath_room': '衛'
    }

    # 身份要求 listing all of them means the house is open to anyone
    all_tenants = {'學生', '上班族', '家庭'}

    def default_parse_detail(self, response):
        house_id = response.meta['rental'].id

        if response.status == 400 or response.url == 'about:blank':
            self.logger.error("I'm getting blocked -___-")
        elif response.status != 200:
            self.logger.info(
                'House {} not found by receiving status code {}'
                .format(house_id, response.status)
            )
            yield GenericHouseItem(
                vendor=self.vendor,
                vendor_house_id=house_id,
                deal_status=enums.DealStatusType.NOT_FOUND
            )
        else:
            # regular 200 response
            # response = response.replace(encoding='utf-8')
            # with open('detail-{}.html'.format(house_id), 'w', encoding='utf-8') as f:
            #     f.write(response.text)

            yield RawHouseItem(
                house_id=house_id,
                vendor=self.vendor,
                is_list=False,
                raw=response.text
            )

            # check existence of house detail page
            error_info = css(response, '.error-info')
            # if error info is not empty, then the house is not found
            if error_info:
                yield GenericHouseItem(
                    vendor=self.vendor,
                    vendor_house_id=house_id,
                    deal_status=enums.DealStatusType.NOT_FOUND
                )
                return None

            # parse detail page in best effort
            detail_dict = get_detail_raw_attrs(response)

            # transform to generic house item
            detail_dict['house_id'] = house_id

            yield RawHouseItem(
                house_id=house_id,
                vendor=self.vendor,
                is_list=False,
                dict=detail_dict
            )

            yield GenericHouseItem(
                **self.gen_detail_shared_attrs(detail_dict)
            )
            

    def get_shared_price(self, detail_dict, basic_info):
        ret = {}

        price = clean_number(detail_dict['price'])

        # deposit_type, n_month_deposit
        if 'deposit' in detail_dict:
            deposit = detail_dict['deposit']
            month_deposit = deposit.split('個月')
            if len(month_deposit) == 2:
                ret['deposit_type'] = enums.DepositType.月
                ret['n_month_deposit'] = from_zh_number(month_deposit[0].replace('押金', ''))
                ret['deposit'] = ret['n_month_deposit'] * price
            elif deposit.replace(',', '').isdigit():
                ret['deposit'] = clean_number(deposit)
                n_month = ret['deposit'] / price
                ret['deposit_type'] = enums.DepositType.定額
                ret['n_month_deposit'] = n_month
            elif deposit == '面議':
                ret['deposit_type'] = enums.DepositType.面議
                ret['n_month_deposit'] = None
                ret['deposit'] = None
            else:
                ret['deposit_type'] = enums.DepositType.其他
                ret['n_month_deposit'] = None
                ret['deposit'] = None

        # is_management_fee, monthly_management_fee
        price_includes = misc_of(detail_dict, '租金含')
        mgmt_fee = misc_text_of(detail_dict, '管理費')

        if '管理費' in price_includes:
            ret['is_require_management_fee'] = False
            ret['monthly_management_fee'] = 0
        elif mgmt_fee:
            # could be xxx元/月, --, -, !@$#$%...
            if '元/月' in mgmt_fee:
                ret['is_require_management_fee'] = True
                ret['monthly_management_fee'] = clean_number(mgmt_fee)
            else:
                ret['is_require_management_fee'] = False
                ret['monthly_management_fee'] = 0

        # *_parking*
        parking_str = misc_text_of(detail_dict, '車位租金', '車位費')

        if '車位費' in price_includes:
            ret['has_parking'] = True
            ret['is_require_parking_fee'] = False
            ret['monthly_parking_fee'] = 0
        elif parking_str:
            parking = clean_number(parking_str)
            ret['has_parking'] = True
            if parking:
                ret['is_require_parking_fee'] = True
                ret['monthly_parking_fee'] = parking
            elif '已含' in parking_str:
                ret['is_require_parking_fee'] = False
                ret['monthly_parking_fee'] = 0
            elif '費用另計' in parking_str:
                ret['is_require_parking_fee'] = True
                ret['monthly_parking_fee'] = 0
            elif parking_str == '無':
                ret['has_parking'] = False

        # per ping price
        if 'floor_ping' in basic_info:
            # no int for get() XD
            mgmt = ret.get('monthly_management_fee', 0)
            parking = ret.get('monthly_parking_fee', 0)
            total_price = price + mgmt + parking
            ret['per_ping_price'] = total_price / basic_info['floor_ping']

        return ret

    def get_shared_basic(self, detail_dict):
        ret = {}

        # region xx市/xx區/物件類型
        breadcrumb = get(detail_dict, 'breadcrumb', default=[])

        if len(breadcrumb) < 2:
            raise ShortBreadcrumbError(
                'house {} served with breadcrumb {}, cannot tell regions — '
                'leave the request in queue for a later batch to retry'.format(
                    detail_dict['house_id'],
                    breadcrumb
                )
            )

        top_region = breadcrumb[0]
        sub_region = breadcrumb[1]

        ret['top_region'] = self.get_enum(
            enums.TopRegionType,
            detail_dict['house_id'],
            top_region
        )

        ret['sub_region'] = self.get_enum(
            enums.SubRegionType,
            detail_dict['house_id'],
            '{}{}'.format(
                top_region,
                sub_region
            )
        )

        ret['rough_address'] = get(detail_dict, 'rough_address')

        # deal_status
        deal_day = detail_dict['deal_time'] or 0
        if deal_day:
            deal_day = clean_number(deal_day[0])

        if deal_day > 0:
            # Issue #15, update only deal_status in crawler
            # let `syncstateful` to update the rest
            ret['deal_status'] = enums.DealStatusType.DEAL
        else:
            # Issue #14, always update deal status since item may be reopened
            ret['deal_status'] = enums.DealStatusType.OPENED

        # property type; a 2-level breadcrumb still tells regions but not the
        # type — fall back to the one from .pattern like the legacy sentinel
        property_type = breadcrumb[2] if len(breadcrumb) >= 3 else '__UNKNOWN__'
        if property_type != '__UNKNOWN__':
            ret['property_type'] = self.get_enum(
                enums.PropertyType,
                detail_dict['house_id'],
                property_type
            )
        elif 'property_type' in detail_dict:
            ret['property_type'] = self.get_enum(
                enums.PropertyType,
                detail_dict['house_id'],
                detail_dict['property_type']
            )

        if ret.get('property_type') == enums.PropertyType.車位:
            return ret

        # building_type, 公寓 / 電梯大樓 / 透天
        if 'building_type' in detail_dict:
            building_type = detail_dict['building_type']
            if building_type == '別墅' or building_type == '透天厝':
                ret['building_type'] = enums.BuildingType.透天
            elif building_type == '住宅大樓' or building_type == '電梯大樓':
                ret['building_type'] = enums.BuildingType.電梯大樓
            else:
                ret['building_type'] = self.get_enum(
                    enums.BuildingType,
                    detail_dict['house_id'],
                    building_type
                )

        # is_rooftop, floor, total_floor
        # TODO: use title to detect rooftop
        if 'floor' in detail_dict:
            # floor_info = 1F/2F or 頂樓加蓋/2F or 整棟/2F or 平面式, 1F~3F/3F
            floor_info = detail_dict['floor'].split('/')
            floor = clean_number(floor_info[0].split('~')[0])  # for 1F~3F
            total_floor = 0
            if len(floor_info) >= 2:
                total_floor = clean_number(floor_info[1])
            # mark 整棟 as floor 0
            ret['floor'] = 0
            ret['total_floor'] = total_floor
            ret['is_rooftop'] = False

            # 頂樓加蓋 in the old template, 頂層加蓋 since 2026
            if floor_info[0] in ROOFTOP_FLOORS:
                ret['is_rooftop'] = True
                ret['floor'] = ret['total_floor'] + 1
            elif 'B' in floor_info[0] and floor:
                # basement
                ret['floor'] = floor * -1
            elif floor:
                ret['floor'] = floor

            ret['dist_to_highest_floor'] = ret['total_floor'] - ret['floor']

        if 'floor_ping' in detail_dict:
            ret['floor_ping'] = clean_number(detail_dict['floor_ping'])

        n_balcony = 0
        # When no 陽台， name is '陽台'
        # When there's 陽台， name is 'x陽台'...
        # ...except 591 also lists a plain '陽台' as provided, meaning one.
        # Without the fallback n_balcony would be None, which then breaks
        # apt_feature_code and drops the whole house.
        for name in detail_dict['supported_facility']:
            if name.endswith('陽台'):
                n_balcony = clean_number(name) or 1
        ret['n_balcony'] = n_balcony

        if ret.get('property_type') == enums.PropertyType.整層住家:
            # 2房1廳1衛
            ret['n_bed_room'] = 0
            ret['n_living_room'] = 0
            ret['n_bath_room'] = 0

            apt_parts = re.findall(
                r'(\d)([^\d]+)',
                detail_dict['property_type']
            )
            if len(apt_parts) >= 1:
                ret['n_bed_room'] = clean_number(apt_parts[0])

            if len(apt_parts) >= 2:
                ret['n_living_room'] = clean_number(apt_parts[1])

            if len(apt_parts) >= 3:
                ret['n_bath_room'] = clean_number(apt_parts[2])

            ret['apt_feature_code'] = '{:02d}{:02d}{:02d}{:02d}'.format(
                ret['n_balcony'],
                ret['n_bath_room'],
                ret['n_bed_room'],
                ret['n_living_room']
            )

        return ret

    def count_keyword_in_list(self, haystack, the_list, must_not_match=False):
        counter = 0
        if must_not_match:
            for item in the_list:
                if haystack in item and haystack != item:
                    counter += 1
        else:
            for item in the_list:
                if haystack in item:
                    counter += 1
        return counter

    def get_shared_environment(self, detail_dict):
        # additional fee
        price_includes = misc_of(detail_dict, '租金含')

        additional_fee = {
            'eletricity': '電費' not in price_includes,
            'water': '水費' not in price_includes,
            'gas': '瓦斯費' not in price_includes,
            'internet': '網路' not in price_includes,
            'cable_tv': '第四台' not in price_includes
        }

        # living_functions & transportation
        # remove for now, as 2021 591 API doesn't provide necessary info #89

        ret = {
            'additional_fee': additional_fee
        }

        return ret

    def get_shared_boolean_info(self, detail_dict):
        ret = {}

        # 房屋守則 used to be one paragraph. The 2026 template splits it into
        # labelled rows - 身份要求 / 性別 / 養寵物 / 開伙 - so read the whole
        # section as one text and keep matching keywords on it.
        service = get(detail_dict, 'service', default={}) or {}
        if isinstance(service, dict):
            rule = ' '.join(str(value) for value in service.values())
        else:
            rule = str(service)

        tags = get(detail_dict, 'tags', default=[])

        # has_tenant_restriction
        # 2021 591 API use more soft word, with the same meaning...
        # 適合學生 === 限學生
        # 適合上班族及家庭 === 限上班族及家庭
        # 2026 591 lists who the house is for, 學生、上班族、家庭 being all of
        # them, so anything shorter than that is a restriction.
        tenants = service.get('身份要求') if isinstance(service, dict) else None
        ret['has_tenant_restriction'] = '適合' in rule or (
            bool(tenants) and set(tenants.split('、')) != self.all_tenants
        )

        # has_gender_restriction
        # 2021 591 API use 此房屋限男生租住 / 此房屋限女生租住 / 此房屋男女皆可租住 / None
        ret['has_gender_restriction'] = False
        ret['gender_restriction'] = enums.GenderType.不限
        if '此房屋限' in rule:
            if '女生' in rule:
                ret['has_gender_restriction'] = True
                ret['gender_restriction'] = enums.GenderType.女
            elif '男生' in rule:
                ret['has_gender_restriction'] = True
                ret['gender_restriction'] = enums.GenderType.男

        # can_cook
        if '不可開伙' in rule:
            ret['can_cook'] = False
        elif '可開伙' in rule or '可開伙' in tags:
            ret['can_cook'] = True
        else:
            ret['can_cook'] = None

        # allow pet
        if '不可養寵物' in rule:
            ret['allow_pet'] = False
        elif '可養寵物' in rule or '可養寵物' in tags:
            ret['allow_pet'] = True
        else:
            ret['allow_pet'] = None

        # has_perperty_registration
        # 已辦理產權登記 in the old template, 房屋已辦產權登記 in the 2026 one,
        # and the row is missing altogether on some houses
        registration = misc_text_of(detail_dict, '產權登記')
        ret['has_perperty_registration'] = '已辦' in registration

        return ret

    def get_shared_misc(self, detail_dict):
        ret = {}

        # rough_coordinate
        position_str = get(detail_dict, 'rough_coordinate')
        if not position_str:
            position_str = '0,0'
        position = position_str.split(',')
        coordinate = [
            Decimal(position[0]),
            Decimal(position[1])
        ]

        if (coordinate[0] > 20 and coordinate[0] < 30):
            # simple lat validator
            # 東沙島 = 20.7036471,116.719958
            # 馬祖 = 26.402385,119.8869727
            ret['rough_coordinate'] = coordinate

        # facilities
        facilities = {}
        for item in get(detail_dict, 'supported_facility', default=[]):
            if '陽台' in item:
                continue
            facilities[item] = True

        for item in get(detail_dict, 'unsupported_facility', default=[]):
            if '陽台' in item:
                continue
            facilities[item] = False

        ret['facilities'] = facilities

        # contact, agent, and author
        # 屋主: 陳先生 / 仲介: 戴先生, no contact card at all on some pages
        contact_name = get(detail_dict, 'author_name') or ''
        [role, _, author] = contact_name.partition(': ')
        phone = get(detail_dict, 'author_phone')

        if not phone or not author:
            # when it's dealt, phone become empty, do not update author
            return ret

        if role == '仲介':
            ret['contact'] = enums.ContactType.房仲
        else:
            ret['contact'] = self.get_enum(
                enums.ContactType,
                detail_dict['house_id'],
                role
            )

        if phone != '':
            ret['author'] = phone.replace('-', '')
        else:
            ret['author'] = author

        if ret['contact'] == enums.ContactType.房仲:
            ret['agent_org'] = get(detail_dict, 'agent_org')
            if ret['agent_org'] == '經紀業: 不動產經紀業':
                ret['agent_org'] = '未認證'

        return ret

    def gen_detail_shared_attrs(self, detail_dict):
        price_range = parse_price(detail_dict['price'])
        detail_dict['price'] = price_range['monthly_price']
        basic_info = self.get_shared_basic(detail_dict)

        ret = {
            'vendor': self.vendor,
            'vendor_house_id': detail_dict['house_id'],
            'monthly_price': detail_dict['price'],
            **price_range,
            **basic_info,
        }

        if basic_info['property_type'] == enums.PropertyType.車位:
            self.logger.info(
                'Skip {} as it is parking lot'.format(detail_dict['house_id'],)
            )
            return ret

        price_info = self.get_shared_price(detail_dict, basic_info)
        env_info = self.get_shared_environment(detail_dict)
        boolean_info = self.get_shared_boolean_info(detail_dict)
        misc_info = self.get_shared_misc(detail_dict)

        ret = {
            **ret,
            **price_info,
            **env_info,
            **boolean_info,
            **misc_info,
        }

        return ret
