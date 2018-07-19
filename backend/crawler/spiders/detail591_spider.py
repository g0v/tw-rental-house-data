import re
from functools import partial
from django.utils import timezone
from ..items import GenericHouseItem, RawHouseItem
from .house_spider import HouseSpider
import traceback
from rental import enums
from rental.models import House
from django.db import transaction

# TODO: mark 404, rented and avoid duplicated update

# TODO: tools porting

class Detail591Spider(HouseSpider):
    name = "detail591"
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
        'n_balcony': '陽台',
        'n_bath_room': '衛'
    }

    def __init__(self, **kwargs):
        super().__init__(
            vendor='591 租屋網',
            is_list=False,
            request_generator=self.gen_request_params,
            response_parser=self.parse_detail,
            **kwargs
        )
        self.BASE_URL = self.vendor.site_url

    def gen_request_params(self, seed):
        url = "{}/rent-detail-{}.html".format(self.BASE_URL, seed['house_id'])

        return {
            'url': url,
            'meta': {
                'seed': seed,
                'handle_httpstatus_list': [400, 404, 302, 301]
            }
        }

    def start_requests(self):

        if not self.has_request():
            # find all opened houses and crawl all of them
            houses = House.objects.filter(
                deal_status = enums.DealStatusType.OPENED
            ).values('vendor_house_id')

            self.logger.info('generating request: {}'.format(houses.count()))

            with transaction.atomic():
                try:
                    for house in houses:
                        self.gen_persist_request({
                            'house_id': house['vendor_house_id']
                        })
                except:
                    traceback.print_exc()

        while True:
            next_request = self.next_request()
            if next_request:
                yield next_request
            else:
                break

    def dict_from_tuple(self, keys, values):
        min_length = min(len(keys), len(values))
        ret = {}

        for i in range(min_length):
            ret[keys[i]] = values[i]

        return ret

    def split_string_to_dict(self, string, seperator):
        tokens = string.split(seperator)
        if len(tokens) >= 2:
            return {tokens[0]: tokens[1]}
        else:
            return None

    def collect_dict(self, response):
        # title
        title = self.css_first(response, '.houseInfoTitle::text')

        # region 首頁/租屋/xx市/xx區
        breadcromb = self.css(response, '#propNav a::text')
        if len(breadcromb) >= 4:
            top_region = breadcromb[2]
            sub_region = breadcromb[3]
        else:
            top_region = '__UNKNOWN__'
            sub_region = '__UNKNOWN__'

        # rough address
        address = self.css_first(response, '#propNav .addr::text')

        # image, it's in a hidden input
        imgs = self.css_first(response, '#hid_imgArr::attr(value)')\
            .replace('"', '').split(',')

        if imgs[0] == "":
            imgs.pop(0)

        # top meta, including 押金, 法定用途, etc..
        top_meta_keys = self.css(response, '.labelList-1 .one::text')
        top_meta_values = self.css(response, '.labelList-1 .two em::text')
        top_metas = self.dict_from_tuple(top_meta_keys, top_meta_values)

        if '身份要求' in top_metas:
            top_metas['身份要求'] = top_metas['身份要求'].split('、')

        # facilities, including 衣櫃、沙發, etc..
        fa_status = self.css(response, '.facility li span::attr(class)')
        fa_text = self.css(response, '.facility li::text')
        fa = []
        without_fa = []
        for index, key in enumerate(fa_text):
            if fa_status[index] != 'no':
                fa.append(key)
            else:
                without_fa.append(key)

        # environment
        # <p><strong>生活機能</strong>：近便利商店；傳統市場；夜市</p>
        env_keys = self.css(response, '.lifeBox > p strong::text')
        env_desps = self.css(response, '.lifeBox > p::text')
        env_desps = list(map(lambda desp: desp.replace('：', '').split('；'), env_desps))
        env = self.dict_from_tuple(env_keys, env_desps)

        # neighbor
        nei_selector = response.css('.lifeBox.community')
        nei = {}
        if nei_selector:
            nei['name'] = self.css_first(nei_selector, '.communityName a::text')
            nei['desp'] = self.css_first(nei_selector, '.communityIntroduce::text')
            nei['url'] = self.BASE_URL +\
                self.css_first(nei_selector, '.communityIntroduce a::attr(href)')
            nei_keys = self.css(nei_selector, '.communityDetail p::text')
            nei_values = self.css(nei_selector, '.communityDetail p > *::text')
            nei['info'] = self.dict_from_tuple(nei_keys, nei_values)

        # sublets 分租套房、雅房
        sublets_keys = self.css(response, '.list-title span::text')
        sublets_list = response.css('.house-list')
        sublets = []
        for sublet in sublets_list:
            texts = self.css(sublet, 'li *::text')
            sublet_dict = self.dict_from_tuple(sublets_keys, texts)
            if '租金' in sublet_dict:
                sublet_dict['租金'] = self.clean_number(sublet_dict['租金'])
            if '坪數' in sublet_dict:
                sublet_dict['坪數'] = self.clean_number(sublet_dict['坪數'])

            sublets.append(sublet_dict)

        # desp
        desp = self.css(response, '.houseIntro *::text')

        # gps
        # TODO

        # q and a
        # TODO
        # TODO: format correct

        # price
        price = self.css_first(response, '.price i::text')

        # built-in facility
        price_includes = self.css_first(
            response,
            '.detailInfo .price+.explain::text'
        ).split('/')

        # lease status
        is_deal = len(response.css('.filled').extract()) > 0
        # house_state = 'OPENED'
        # deal_at = None
        # if is_deal:
        #     house_state = 'DEAL'
        #     deal_at = timezone.localtime()

        # side meta
        sides = self.css(response, '.detailInfo .attr li::text')
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
            side_metas['坪數'] = self.clean_number(side_metas['坪數'])
        if '權狀坪數' in side_metas:
            side_metas['權狀坪數'] = self.clean_number(side_metas['權狀坪數'])

        # due day
        due_day = self.css_first(response, '.explain .ft-rt::text')
        due_day = due_day.replace('有效期：', '')

        # owner
        owner = {}
        owner['name'] = self.css_first(response, '.avatarRight i::text')
        owner['comment'] = self.css_first(response, '.avatarRight div::text')
        agent_info = self.css(response, '.avatarRight .auatarSonBox p::text')
        make_agent_info = partial(self.split_string_to_dict, seperator='：')
        agent_info = list(map(make_agent_info, agent_info))
        owner['isAgent'] = len(agent_info) > 0
        owner['agent'] = agent_info

        return {
            'house_id': response.meta['seed']['house_id'],
            'n_views': self.css_first(response, '.pageView b::text'),
            'top_region': top_region,
            'sub_region': sub_region,
            'address': address,
            'title': title,
            'imgs': imgs,
            'top_metas': top_metas,
            'facilities': fa,
            'without_facilities': without_fa,
            'environment': env,
            'sublets': sublets,
            'neighbor': nei,
            'desp': desp,
            'price': price,
            'price_includes': price_includes,
            'is_deal': is_deal,
            'side_metas': side_metas,
            'due_day': due_day,
            'owner': owner
        }

    def from_zh_number(self, zh_number):
        if zh_number in self.zh_number_dict:
            return self.zh_number_dict[zh_number]
        else:
            raise Exception('ZH number {} not defined.'.format(zh_number))

    def get_shared_price(self, detail_dict, house, basic_info):
        ret = {}

        # deposit_type, n_month_deposit
        if '押金' in detail_dict['top_metas']:
            deposit = detail_dict['top_metas']['押金']
            month_deposit = deposit.split('個月')
            if len(month_deposit) == 2:
                ret['deposit_type'] = enums.DepositType.月
                ret['n_month_deposit'] = self.from_zh_number(month_deposit[0])
                ret['deposit'] = ret['n_month_deposit'] * detail_dict['price']
            elif deposit.replace(',', '').isdigit():
                ret['deposit'] = self.clean_number(deposit)
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
        if '管理費' in detail_dict['price_includes']:
            ret['is_require_management_fee'] = False
            ret['monthly_management_fee'] = 0
        elif '管理費' in detail_dict['top_metas']:
            mgmt_fee = detail_dict['top_metas']['管理費']
            # could be xxx元/月, --, -, !@$#$%...
            if '元/月' in mgmt_fee:
                ret['is_require_management_fee'] = True
                ret['monthly_management_fee'] = self.clean_number(mgmt_fee)
            else:
                ret['is_require_management_fee'] = False
                ret['monthly_management_fee'] = 0

        # *_parking*
        if '車 位' in detail_dict['top_metas']:
            parking_str = detail_dict['top_metas']['車 位']
            parking = self.clean_number(parking_str)

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
            elif '無' == parking_str:
                ret['has_parking'] = False

        # per ping price
        if 'floor_ping' in basic_info:
            mgmt = ret.get('monthly_management_fee', 0)
            parking = ret.get('monthly_parking_fee', 0)
            price = detail_dict['price']
            total_price = price + mgmt + parking
            ret['per_ping_price'] = total_price / basic_info['floor_ping']

        return ret

    def get_shared_basic(self, detail_dict, house):
        ret = {}

        # top_region, sub_region
        if 'top_region' in detail_dict:
            ret['top_region'] = self.get_enum(
                enums.TopRegionType,
                detail_dict['house_id'],
                detail_dict['top_region']
            )
            
            ret['sub_region'] = self.get_enum(
                enums.SubRegionType,
                detail_dict['house_id'],
                '{}{}'.format(
                    detail_dict['top_region'],
                    detail_dict['sub_region']
                )
            )

        if 'address' in detail_dict:
            ret['rough_address'] = detail_dict['address']

        # deal_status, deal_time, n_day_deal
        if detail_dict['is_deal']:
            now = timezone.now()
            time_taken = now - house.created
            elipse_day = 1 if time_taken.seconds > 0 else 0
            ret['deal_status'] = enums.DealStatusType.DEAL
            ret['deal_time'] = now
            ret['n_day_deal'] = time_taken.days + elipse_day

        # building_type, 公寓 / 電梯大樓 / 透天
        if '型態' in detail_dict['side_metas']:
            building_type = detail_dict['side_metas']['型態']
            if building_type == '別墅' or building_type == '透天厝':
                ret['building_type'] = enums.BuildingType.透天
            elif building_type == '住宅大樓':
                ret['building_type'] = enums.BuildingType.電梯大樓
            else:
                ret['building_type'] = self.get_enum(
                    enums.BuildingType,
                    detail_dict['house_id'],
                    building_type
                )

        # property type
        if '現況' in detail_dict['side_metas']:
            ret['property_type'] = self.get_enum(
                enums.PropertyType,
                detail_dict['house_id'],
                detail_dict['side_metas']['現況']
            )

        # is_rooftop, floor, total_floor
        # TODO: use title to detect rooftop
        if '樓層' in detail_dict['side_metas']:
            # floor_info = 1F/2F or 頂樓加蓋/2F or 整棟/2F
            floor_info = detail_dict['side_metas']['樓層'].split('/')
            floor = self.clean_number(floor_info[0])
            ret['floor'] = 0
            ret['total_floor'] = self.clean_number(floor_info[1])
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

        if '坪數' in detail_dict['side_metas']:
            ret['floor_ping'] = self.clean_number(
                detail_dict['side_metas']['坪數'])

        if '格局' in detail_dict['side_metas']:
            apt_feature = detail_dict['side_metas']['格局']

            for name in self.apt_features:
                if self.apt_features[name] in apt_feature:
                    ret[name] = self.clean_number(
                        apt_feature[self.apt_features[name]])
                else:
                    ret[name] = 0

            ret['apt_feature_code'] = '{:02d}{:02d}{:02d}{:02d}'.format(
                ret['n_balcony'],
                ret['n_bath_room'],
                ret['n_bed_room'],
                ret['n_living_room']
            )

        # TODO: rough_address, rough_gps

        return ret

    def count_keyword_in_list(self, haystack, list, must_not_match=False):
        counter = 0
        if must_not_match:
            for item in list:
                if haystack in item and haystack != item:
                    counter += 1
        else:
            for item in list:
                if haystack in item:
                    counter += 1
        return counter

    def get_shared_environment(self, detail_dict, house):
        # additional fee
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
            tp = detail_dict['environment']['附近交通']
            transportation = {
                'subway': self.count_keyword_in_list('捷運站', tp),
                'bus': self.count_keyword_in_list('公車站', tp) +
                        self.count_keyword_in_list('路', tp),
                'train': self.count_keyword_in_list('火車站', tp),
                'hsr': self.count_keyword_in_list('高速鐵路', tp),
                'public_bike': self.count_keyword_in_list('bike', lower_desp)
            }

        ret = {
            'additional_fee': additional_fee,
            'living_functions': living_functions,
            'transportation': transportation
        }

        return ret

    def get_shared_boolean_info(self, detail_dict, house):
        ret = {}

        # has_tenant_restriction
        ret['has_tenant_restriction'] = False
        if '身份要求' in detail_dict['top_metas']:
            if len(detail_dict['top_metas']['身份要求']) > 0:
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

    def get_shared_misc(self, detail_dict, house):
        ret = {}

        # facilities
        facilities = {}
        for item in detail_dict['facilities']:
            facilities[item] = True

        for item in detail_dict['without_facilities']:
            facilities[item] = False

        ret['facilities'] = facilities

        # contact and agent
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

        return ret

    def gen_shared_attrs(self, detail_dict, house=None):

        if house == None:
            house = House.objects.get(
                vendor = self.vendor,
                vendor_house_id = detail_dict['house_id']
            )

        detail_dict['price'] = self.clean_number(detail_dict['price'])

        detail_dict['price_includes'] = list(map(
            lambda x: x.replace('含', ''),
            detail_dict['price_includes']
        ))

        if '生活機能' in detail_dict['environment']:
            detail_dict['environment']['生活機能'] = list(map(
                lambda x: x.replace('近', ''),
                detail_dict['environment']['生活機能']
            ))

        if '附近交通' in detail_dict['environment']:
            detail_dict['environment']['附近交通'] = list(map(
                lambda x: re.sub('[ 　]', '', x.replace('近', '')),
                detail_dict['environment']['附近交通']
            ))

        ret = {
            'vendor': self.vendor,
            'vendor_house_id': detail_dict['house_id'],
            'monthly_price': detail_dict['price'],
            'imgs': detail_dict['imgs']
        }

        basic_info = self.get_shared_basic(detail_dict, house)
        price_info = self.get_shared_price(detail_dict, house, basic_info)
        env_info = self.get_shared_environment(detail_dict, house)
        boolean_info = self.get_shared_boolean_info(detail_dict, house)
        misc_info = self.get_shared_misc(detail_dict, house)

        ret = {
          **ret,
          **price_info,
          **basic_info,
          **env_info,
          **boolean_info,
          **misc_info
        }

        return ret

    def parse_detail(self, response):
        if response.status == 400:
            self.logger.info("I'm getting blocked -___-")
        elif response.status != 200:
            self.logger.info(
                'House {} not found by receiving status code {}'
                .format(response.meta['seed']['house_id'], response.status)
            )
            yield GenericHouseItem(
                vendor=self.vendor,
                vendor_house_id=response.meta['seed']['house_id'],
                deal_status=enums.DealStatusType.NOT_FOUND
            )
        else:
            # regular 200 response
            yield RawHouseItem(
                house_id=response.meta['seed']['house_id'],
                vendor=self.vendor,
                is_list=False,
                raw=response.body
            )

            detail_dict = self.collect_dict(response)

            yield RawHouseItem(
                house_id=response.meta['seed']['house_id'],
                vendor=self.vendor,
                is_list=False,
                dict=detail_dict
            )

            yield GenericHouseItem(
                **self.gen_shared_attrs(detail_dict)
            )

        if response.status != 400:
            yield True
