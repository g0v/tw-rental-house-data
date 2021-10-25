import json
import re
from functools import reduce
from urllib.parse import urlparse, parse_qs
from decimal import Decimal
from functools import partial
from scrapy_twrh.spiders import enums
from scrapy_twrh.spiders.util import clean_number
from scrapy_twrh.items import RawHouseItem, GenericHouseItem
from .request_generator import RequestGenerator
from .util import parse_price

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

class DetailMixin(RequestGenerator):
    zh_number_dict = {
        '零': 0,
        '一': 1,
        '二': 2,
        '三': 3,
        '四': 4,
        '五': 5,
        '六': 6,
        '七': 7,
        '八': 8,
        '九': 9,
        '十': 10
    }

    apt_features = {
        'n_living_room': '廳',
        'n_bed_room': '房',
        'n_bath_room': '衛'
    }

    def default_parse_detail(self, response):
        house_id = response.meta['rental'].id

        if response.status == 400:
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
            yield RawHouseItem(
                house_id=house_id,
                vendor=self.vendor,
                is_list=False,
                raw=response.body
            )
            jsonResp = json.loads(response.text)
            if 'data' not in jsonResp:
                self.logger.error('Invalid detail response for 591 house: {}'
                    .format(response.meta['rental'].id)
                )
                return False

            detail_dict = jsonResp['data']
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

    def css(self, base, selector, default=None, deep_text=False):
        # keep this for now, in case we meet this issue again.. #89
        # Issue #30, we may get innerHTML like "some of <kkkk></kkkk>target <qqq></qqq>string"
        # deep_text=True retrieve text in the way different from ::text,
        # which will also get all child text.
        if deep_text:
            ret = map(lambda dom: ''.join(dom.css('*::text').extract()), base.css(selector))
        else:
            ret = base.css(selector).extract()

        if not ret:
            ret = [] if default is None else default

        ret = self.clean_string(ret)
        return list(ret)

    def clean_string(self, strings):
        # remove empty and strip
        strings = filter(lambda str: str.replace(u'\xa0', '').strip(), strings)
        strings = map(lambda str: str.replace(u'\xa0', '').strip(), strings)
        return strings

    def from_zh_number(self, zh_number):
        if zh_number in self.zh_number_dict:
            return self.zh_number_dict[zh_number]
        else:
            raise Exception('ZH number {} not defined.'.format(zh_number))

    def get_shared_price(self, detail_dict, basic_info):
        ret = {}

        cost_data = list_to_dict(
            get(detail_dict, 'costData.data', default=[])
        )

        # deposit_type, n_month_deposit
        if '押金' in cost_data:
            deposit = cost_data['押金']
            month_deposit = deposit.split('個月')
            if len(month_deposit) == 2:
                ret['deposit_type'] = enums.DepositType.月
                ret['n_month_deposit'] = self.from_zh_number(month_deposit[0])
                ret['deposit'] = ret['n_month_deposit'] * detail_dict['price']
            elif deposit.replace(',', '').isdigit():
                ret['deposit'] = clean_number(deposit)
                n_month = ret['deposit'] / detail_dict['price']
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
        price_includes = []
        if '租金含' in cost_data:
            price_includes = cost_data['租金含'].split('、')

        if '管理費' in price_includes:
            ret['is_require_management_fee'] = False
            ret['monthly_management_fee'] = 0
        elif '管理費' in cost_data:
            mgmt_fee = cost_data['管理費']
            # could be xxx元/月, --, -, !@$#$%...
            if '元/月' in mgmt_fee:
                ret['is_require_management_fee'] = True
                ret['monthly_management_fee'] = clean_number(mgmt_fee)
            else:
                ret['is_require_management_fee'] = False
                ret['monthly_management_fee'] = 0

        # *_parking*
        if '車位費' in price_includes:
            ret['has_parking'] = True
            ret['is_require_parking_fee'] = False
            ret['monthly_parking_fee'] = 0
        elif '車位費' in cost_data:
            parking_str = cost_data['車位費']
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
            mgmt = ret.get('monthly_management_fee', 0)
            parking = ret.get('monthly_parking_fee', 0)
            price = detail_dict['price']
            total_price = price + mgmt + parking
            ret['per_ping_price'] = total_price / basic_info['floor_ping']

        return ret

    def get_shared_basic(self, detail_dict):
        ret = {}

        # region xx市/xx區/物件類型
        breadcrumb = list_to_dict(
            get(detail_dict, 'breadcrumb', default=[]),
            name_field='query',
            value_field='name'
        )
        top_region = get(breadcrumb, 'region', default='__UNKNOWN__')
        sub_region = get(breadcrumb, 'section', default='__UNKNOWN__')

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

        ret['rough_address'] = get(detail_dict, 'favData.address')

        # deal_status
        dealDay = get(detail_dict, 'dealTime', 0)
        if dealDay > 0:
            # Issue #15, update only deal_status in crawler
            # let `syncstateful` to update the rest
            ret['deal_status'] = enums.DealStatusType.DEAL
        else:
            # Issue #14, always update deal status since item may be reopened
            ret['deal_status'] = enums.DealStatusType.OPENED

        infoSection = list_to_dict(get(detail_dict, 'info', default=[]))

        # building_type, 公寓 / 電梯大樓 / 透天
        if '型態' in infoSection:
            building_type = infoSection['型態']
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

        # property type
        if '類型' in infoSection:
            ret['property_type'] = self.get_enum(
                enums.PropertyType,
                detail_dict['house_id'],
                infoSection['類型']
            )
        elif '格局' in infoSection:
            ret['property_type'] = enums.PropertyType.整層住家

        # is_rooftop, floor, total_floor
        # TODO: use title to detect rooftop
        if '樓層' in infoSection:
            # floor_info = 1F/2F or 頂樓加蓋/2F or 整棟/2F
            floor_info = infoSection['樓層'].split('/')
            floor = clean_number(floor_info[0])
            # mark 整棟 as floor 0
            ret['floor'] = 0
            ret['total_floor'] = clean_number(floor_info[1])
            ret['is_rooftop'] = False

            if floor_info[0] == '頂樓加蓋':
                ret['is_rooftop'] = True
                ret['floor'] = ret['total_floor'] + 1
            elif 'B' in floor_info[0] and floor:
                # basement
                ret['floor'] = -floor
            elif floor:
                ret['floor'] = floor

            ret['dist_to_highest_floor'] = ret['total_floor'] - ret['floor']

        if '坪數' in infoSection:
            ret['floor_ping'] = clean_number(infoSection['坪數'])

        facilityKeys = list_to_dict(
            get(detail_dict, 'service.facility'),
            name_field='key',
            # For 陽台 only, 
            # When no 陽台， name is '陽台'
            # When there's 陽台， name is 'x陽台'...
            value_field='name'
        )
        nBalcony = clean_number(get(facilityKeys, 'balcony', default=''))
        ret['n_balcony'] = nBalcony or 0

        if '格局' in infoSection:
            apt_parts = re.findall(
                r'(\d)([^\d]+)',
                infoSection['格局']
            )
            apt_feature = {}
            for part in apt_parts:
                apt_feature[part[1]] = part[0]

            for name in self.apt_features:
                if self.apt_features[name] in apt_feature:
                    ret[name] = clean_number(
                        apt_feature[self.apt_features[name]])
                else:
                    ret[name] = 0

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
        cost_data = list_to_dict(get(detail_dict, 'costData.data'))
        price_includes = []
        if '租金含' in cost_data:
            price_includes = cost_data['租金含'].split('、')

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
        features = list_to_dict(
            get(detail_dict, 'tags', default=[]),
            name_field='value',
            value_field='id'
        )

        # has_tenant_restriction
        rule = get(detail_dict, 'service.rule')

        # 2021 591 API use more soft word, with the same meaning...
        # 適合學生 === 限學生
        # 適合上班族及家庭 === 限上班族及家庭
        ret['has_tenant_restriction'] = '適合' in rule

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
        elif '可開伙' in features:
            ret['can_cook'] = True
        else:
            ret['can_cook'] = None

        # allow pet
        if '不可養寵物' in rule:
            ret['allow_pet'] = False
        elif '可養寵物' in features:
            ret['allow_pet'] = True
        else:
            ret['allow_pet'] = None

        # has_perperty_registration
        properMetaTitle = get(detail_dict, 'infoData.title')
        ret['has_perperty_registration'] = properMetaTitle == '房屋已辦產權登記'

        return ret

    def get_shared_misc(self, detail_dict):
        ret = {}

        # rough_coordinate
        position = get(detail_dict, 'positionRound')
        coordinate = [
            Decimal(position['lat']),
            Decimal(position['lng'])
        ]

        if (coordinate[0] > 20 and coordinate[0] < 30):
            # simple lat validator
            # 東沙島 = 20.7036471,116.719958
            # 馬祖 = 26.402385,119.8869727
            ret['rough_coordinate'] = coordinate

        # facilities
        facilities = {}
        for item in get(detail_dict, 'service.facility', default=[]):
            if item['key'] == 'balcony':
                continue
            doProvide = item['active'] == 1
            if item['key'] == 'table_chairs':
                facilities['桌子'] = doProvide
                facilities['椅子'] = doProvide
            else:
                facilities[item['name']] = doProvide

        ret['facilities'] = facilities

        # contact, agent, and author
        owner = get(detail_dict, 'linkInfo', default={})
        if owner['roleName'] == '仲介':
            ret['contact'] = enums.ContactType.房仲
        else:
            ret['contact'] = self.get_enum(
                enums.ContactType,
                detail_dict['house_id'],
                owner['roleName']
            )

        if owner['mobile'] != '':
            ret['author'] = owner['mobile'].replace('-', '')
        else:
            ret['author'] = owner['uid'] or owner['imUid']

        if ret['contact'] == enums.ContactType.房仲:
            ret['agent_org'] = owner['roleTxt'] or owner['certificateTxt']
            if ret['agent_org'] == '經紀業: 不動產經紀業':
                ret['agent_org'] = '未認證'

        return ret

    def gen_detail_shared_attrs(self, detail_dict):
        price_range = parse_price(detail_dict['price'])
        detail_dict['price'] = price_range['monthly_price']
        basic_info = self.get_shared_basic(detail_dict)
        price_info = self.get_shared_price(detail_dict, basic_info)
        env_info = self.get_shared_environment(detail_dict)
        boolean_info = self.get_shared_boolean_info(detail_dict)
        misc_info = self.get_shared_misc(detail_dict)

        ret = {
            'vendor': self.vendor,
            'vendor_house_id': detail_dict['house_id'],
            'monthly_price': detail_dict['price'],
            **price_range,
            **price_info,
            **basic_info,
            **env_info,
            **boolean_info,
            **misc_info,

        }

        return ret
