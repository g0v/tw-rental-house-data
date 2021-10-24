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
from .util import DetailRequestMeta, SITE_URL

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
        meta = response.meta['rental']
        if meta.gps:
            return self.parse_gps_response(response)

        return self.parse_main_response(response)

    def parse_gps_response(self, response):
        house_id = response.meta['rental'].id

        if response.status == 404:
            self.logger.info(
                'GPS {} not found by receiving status code {}'
                .format(house_id, response.status)
            )
            yield True
            return

        gmap_url = self.css_first(response, '#main .propMapBarMap iframe::attr(src)')
        # example //maps.google.com.tw/maps?f=q&hl=zh-TW&q=25.0268980,121.5542323&z=17&output=embed

        parsed_url = urlparse(gmap_url)
        qs = parse_qs(parsed_url.query)
        if 'q' not in qs or not qs['q']:
            self.logger.info(
                'Invalid GPS page in house: {}'
                .format(house_id)
            )
            return

        gps_str = qs['q'][0]
        coordinate = list(map(Decimal, gps_str.split(',')))

        if len(coordinate) == 2:
            yield GenericHouseItem(
                vendor=self.vendor,
                vendor_house_id=house_id,
                rough_coordinate=coordinate
            )

    def parse_main_response(self, response):
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

            # get gps only when the house existed
            # yield self.gen_detail_request(DetailRequestMeta(
            #     house_id,
            #     True
            # ))

    def css_first(self, base, selector, default='', allow_empty=False, deep_text=False):
        # Check how to find if there's missing attribute
        css = self.css(base, selector, [default], deep_text=deep_text)
        if css:
            return css[0]

        if not allow_empty:
            self.logger.info(
                'Fail to get css first from {}({})'.format(
                    base,
                    selector
                )
            )

        return ''

    def css(self, base, selector, default=None, deep_text=False):
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

    def collect_dict(self, response):
        '''
        convert API response into normalized structured data
        without converting string into machine readable format
        '''
        jsonResp = json.loads(response.text)
        if 'data' not in jsonResp:
            self.logger.error('Invalid detail response for 591 house: {}'
                .format(response.meta['rental'].id)
            )
            return {}

        data = jsonResp['data']
        # title
        title = data['title']

        # region xx市/xx區/物件類型
        breadcrumb = data['breadcrumb']
        top_region = '__UNKNOWN__'
        sub_region = '__UNKNOWN__'
        if len(breadcrumb) >= 3:
            if breadcrumb[0]['query'] is 'region':
                top_region = breadcrumb[0]['name']
            if breadcrumb[1]['query'] is 'section':
                sub_region = breadcrumb[1]['name']

        # rough address
        address = get(data, 'favData.address')

        # TODO: get photo urls

        # cost data, including 租金含、押金、管理費
        cost_data = list_to_dict(get(data, 'costData.data'))
        price_includes = []
        if '租金含' in cost_data:
            price_includes = cost_data['租金含'].split('、')

        # TODO: CHECK
        # if '身份要求' in top_metas:
        #     top_metas['身份要求'] = top_metas['身份要求'].split('、')

        # facilities, including 衣櫃、沙發, etc..
        fa = []
        without_fa = []
        for facility in get(data, 'service.facility'):
            if facility['active'] is 1:
                fa.append(facility['name'])
            else:
                without_fa.append(facility['name'])

        # neighbor, gps
        position = get(data, 'positionRound')

        # sublets 分租套房、雅房
        # name, kind, area, floor, price
        sublets = get(data, 'rooms.data')

        # desp
        desp = get(data, 'remark.content')

        # price
        # <div class="price clearfix"><i>14,500 <b>元/月</b></i></div>
        price = get(data, 'price')

        # lease status
        # TODO: CHECK
        # is_deal = len(response.css('.filled').extract()) > 0
        # house_state = 'OPENED'
        # deal_at = None
        # if is_deal:
        #     house_state = 'DEAL'
        #     deal_at = timezone.localtime()

        # side meta

        sides = self.css(response, '.detailInfo .attr li', deep_text=True)
        side_metas = {}
        for side in sides:
            tokens = side.split(':')
            if len(tokens) >= 2:
                side_metas[tokens[0]] = ':'.join(tokens[1::])

        # 格局 :    3房2廳2衛2陽台
        if '格局' in side_metas:
            # TODO: 開放式格局
            parts = re.findall(
                r'(\d)([^\d]+)',
                side_metas['格局']
            )
            parts_dict = {}
            for part in parts:
                parts_dict[part[1]] = part[0]
            side_metas['格局'] = parts_dict
        if '坪數' in side_metas:
            side_metas['坪數'] = clean_number(side_metas['坪數'])
        if '權狀坪數' in side_metas:
            side_metas['權狀坪數'] = clean_number(side_metas['權狀坪數'])

        # due day
        due_day = self.css_first(response, '.explain .ft-rt', deep_text=True)
        due_day = due_day.replace('有效期：', '')

        # owner
        owner = {}
        owner['name'] = self.css_first(response, '.avatarRight i', deep_text=True)
        owner['comment'] = self.css_first(response, '.avatarRight div', deep_text=True)
        agent_info = self.css(response, '.avatarRight .auatarSonBox p', deep_text=True)
        make_agent_info = partial(split_string_to_dict, seperator='：')
        agent_info = list(map(make_agent_info, agent_info))
        owner['isAgent'] = len(agent_info) > 0
        owner['agent'] = agent_info

        phone_ext = self.css_first(response, '.phone-hide .num', deep_text=True, allow_empty=True)
        phone_url = response.css('.phone-hide .num img').xpath('@src').extract_first()

        if phone_ext:
            # phone will be pure text when owner use 591 built-in phone number
            # TODO: check is the ext is identical for the same owner
            owner['id'] = phone_ext
        elif phone_url:
            # or it will be an img, the src would be identical for the same owner
            # url is sth like
            # statics.591.com.tw/tools/showPhone.php?info_data=%2BbRfNLlKoLNhHOKui2zb%2FBxYO6A&type=rLEFMu4XrrpgEw
            parsed_url = urlparse(phone_url)
            qs = parse_qs(parsed_url.query)
            if 'info_data' in qs and qs['info_data']:
                owner['id'] = qs['info_data'][0]
        else:
            # sth strange happened, such as it's already dealt
            # let's try if there's avatar
            avatar = response.css('.userInfo .avatar img').xpath('@src').extract_first()
            if avatar and 'no-photo-new.png' not in avatar:
                owner['id'] = avatar
            else:
                # last try, search description to see if there's phone number
                phone = re.search(r'09[0-9]{8}', ' '.join(desp))
                if phone:
                    phone = phone.group()
                    owner['id'] = phone

        return {
            'house_id': response.meta['rental'].id,
            'n_views': self.css_first(response, '.pageView b', deep_text=True),
            'top_region': top_region,
            'sub_region': sub_region,
            'address': address,
            'title': title,
            'imgs': imgs,
            'facilities': fa,
            'without_facilities': without_fa,
            'sublets': sublets,
            'position': position,
            'desp': desp,
            'price': price,
            'cost': cost_data,
            'price_includes': price_includes,
            # 'is_deal': is_deal,
            'side_metas': side_metas,
            'due_day': due_day,
            'owner': owner
        }

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

        # is_remanagement_fee, monthly_management_fee
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
        # TODO: check new deal status rule
        # if detail_dict['is_deal']:
        #     # Issue #15, update only deal_status in crawler
        #     # let `syncstateful` to update the rest
        #     ret['deal_status'] = enums.DealStatusType.DEAL
        # else:
        #     # Issue #14, always update deal status since item may be reopened
        #     ret['deal_status'] = enums.DealStatusType.OPENED
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
        # if '租金含' in cost_data:
        #     ret['price_includes'] = cost_data['租金含'].split('、')

        price_includes = detail_dict['price_includes']

        additional_fee = {
            'eletricity': '電費' not in price_includes,
            'water': '水費' not in price_includes,
            'gas': '瓦斯費' not in price_includes,
            'internet': '網路' not in price_includes,
            'cable_tv': '第四台' not in price_includes
        }

        # living_functions
        living_functions = {}
        if '生活機能' in detail_dict['environment']:
            living = detail_dict['environment']['生活機能']
            living_functions = {
                'school': '學校' in living,
                'park': '公園綠地' in living,
                'dept_store': '百貨公司' in living,
                'conv_store': '便利商店' in living,
                'traditional_mkt': '傳統市場' in living,
                'night_mkt': '夜市' in living,
                'hospital': '醫療機構' in living,
                # not provided XDDD
                'police_office': False
            }

        lower_desp = []
        for line in detail_dict['desp']:
            lower_desp.append(line.lower())

        transportation = {}
        if '附近交通' in detail_dict['environment']:
            tp_list = detail_dict['environment']['附近交通']
            transportation = {
                'subway': self.count_keyword_in_list('捷運站', tp_list),
                'bus': self.count_keyword_in_list('公車站', tp_list) +
                       self.count_keyword_in_list('路', tp_list),
                'train': self.count_keyword_in_list('火車站', tp_list),
                'hsr': self.count_keyword_in_list('高速鐵路', tp_list),
                'public_bike': self.count_keyword_in_list('bike', lower_desp)
            }

        ret = {
            'additional_fee': additional_fee,
            'living_functions': living_functions,
            'transportation': transportation
        }

        return ret

    def get_shared_boolean_info(self, detail_dict):
        ret = {}

        # has_tenant_restriction
        ret['has_tenant_restriction'] = False
        if '身份要求' in detail_dict['top_metas']:
            if detail_dict['top_metas']['身份要求']:
                ret['has_tenant_restriction'] = True

        # has_gender_restriction
        ret['has_gender_restriction'] = False
        ret['gender_restriction'] = enums.GenderType.不限
        if '性別要求' in detail_dict['top_metas']:
            gender = detail_dict['top_metas']['性別要求']
            if gender == '女生':
                ret['has_gender_restriction'] = True
                ret['gender_restriction'] = enums.GenderType.女
            elif gender == '男生':
                ret['has_gender_restriction'] = True
                ret['gender_restriction'] = enums.GenderType.男
            elif '不限' not in gender and '男女生皆可' not in gender:
                ret['has_gender_restriction'] = True
                ret['gender_restriction'] = enums.GenderType.其他

        # can_cook
        if '開伙' in detail_dict['top_metas']:
            ret['can_cook'] = detail_dict['top_metas']['開伙'] == '可以'
        else:
            ret['can_cook'] = None

        # allow pet
        if '養寵物' in detail_dict['top_metas']:
            ret['allow_pet'] = detail_dict['top_metas']['養寵物'] == '可以'
        else:
            ret['allow_pet'] = None

        # has_perperty_registration
        ret['has_perperty_registration'] = detail_dict['top_metas']\
            .get('產權登記', '') == '已辦'

        return ret

    def get_shared_misc(self, detail_dict):
        ret = {}

        # facilities
        facilities = {}
        for item in detail_dict['facilities']:
            facilities[item] = True

        for item in detail_dict['without_facilities']:
            facilities[item] = False

        ret['facilities'] = facilities

        # contact, agent, and author
        owner = detail_dict['owner']
        if '代理人' in owner['comment']:
            ret['contact'] = enums.ContactType.代理人
        elif owner['isAgent']:
            ret['contact'] = enums.ContactType.房仲
        else:
            ret['contact'] = enums.ContactType.屋主

        if owner['isAgent']:
            agent = {}
            for item in owner['agent']:
                for key in item:
                    agent[key] = item[key]

            if '公司名' in agent:
                ret['agent_org'] = agent['公司名']
            elif '經濟業' in agent:
                ret['agent_org'] = agent['經濟業']
            else:
                ret['agent_org'] = '/'.join(agent.values())

        if 'id' in detail_dict['owner'] and detail_dict['owner']['id']:
            ret['author'] = detail_dict['owner']['id']

        return ret

    def gen_detail_shared_attrs(self, detail_dict):
        detail_dict['price'] = clean_number(detail_dict['price'])
        basic_info = self.get_shared_basic(detail_dict)
        price_info = self.get_shared_price(detail_dict, basic_info)
        # env_info = self.get_shared_environment(detail_dict)
        # boolean_info = self.get_shared_boolean_info(detail_dict)
        # misc_info = self.get_shared_misc(detail_dict)

        ret = {
            'vendor': self.vendor,
            'vendor_house_id': detail_dict['house_id'],
            'monthly_price': detail_dict['price'],
            # 'imgs': detail_dict['imgs'],
            **price_info,
            **basic_info,
            # **env_info,
            # **boolean_info,
            # **misc_info
        }

        # self.logger.info(ret)

        return ret
