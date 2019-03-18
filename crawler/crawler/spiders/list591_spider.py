import json
import scrapy
from ..items import RawHouseItem, GenericHouseItem
from rental.enums import PropertyType, TopRegionType, SubRegionType
from .house_spider import HouseSpider
from .all_591_cities import all_591_cities

class List591Spider(HouseSpider):
    ENDPOINT = 'https://rent.591.com.tw/home/search/rsList?is_new_list=1&type=1&kind=0&searchtype=1'
    SESSION_ENDPOINT = 'https://rent.591.com.tw/?kind=0&region=6'
    N_PAGE = 30
    name = 'list591'

    def __init__(self, **kwargs):
        super().__init__(
            vendor='591 租屋網',
            is_list=True,
            request_generator=self.gen_request_params,
            response_parser=self.parse_list,
            **kwargs
        )

        self.csrf_token = None
        self.session_token = None

    def gen_request_params(self, seed):
        city = seed['region']

        return {
            'url': "{}&region={}&firstRow={}".format(
                self.ENDPOINT,
                city['id'],
                seed['page'] * self.N_PAGE
            ),
            'headers': {
                'Cookie': 'urlJumpIp={}; 591_new_session={};'.format(city['id'], self.session_token),
                'X-CSRF-TOKEN': self.csrf_token
            },
            'priority': self.clean_number(city['id']),
            'meta': {'seed': seed}
        }

    def start_requests(self):
        # 591 require a valid session to start request, #27
        yield scrapy.Request(
            url=self.SESSION_ENDPOINT,
            dont_filter=True,
            callback=self.handle_session_init,
        )

    def handle_session_init(self, response):
        self.csrf_token = response.css('meta[name="csrf-token"]').xpath('@content').extract_first()

        for cookie in response.headers.getlist('Set-Cookie'):
            cookie_tokens = cookie.decode('utf-8').split('; ')
            if cookie_tokens and cookie_tokens[0].startswith('591_new_session='):
                self.session_token = cookie_tokens[0].split('=')[1]
                break

        if not self.has_request() and not self.has_record():
            for region in all_591_cities:
                # let's do DFS
                self.gen_persist_request({
                    'region': region,
                    'page': 0
                })

        while True:
            next_request = self.next_request()
            if next_request:
                yield next_request
            else:
                break

    def get_val(self, house, regular_attr, top_attr=None, clean_number=False):
        ret = None

        if regular_attr in house:
            ret = house[regular_attr]
        elif top_attr in house:
            ret = house[top_attr]

        if clean_number and ret is not None:
            ret = self.clean_number(ret)

        return ret

    def gen_shared_attrs(self, house, seed={}):
        house_id = self.get_val(house, 'id', 'post_id')

        url = '{}/rent-detail-{}.html'.format(
            self.vendor.site_url, house_id)

        if 'region_name' in house:
            # topData doesn't contain region_name for some reason..
            top_region = self.get_enum(
                TopRegionType, house_id, house['region_name'])
        else:
            top_region = self.get_enum(
                TopRegionType, house_id, seed['region']['city'])

        sub_region = self.get_enum(
            SubRegionType,
            house_id,
            '{}{}'.format(
                TopRegionType(top_region).name,
                self.get_val(house, 'section_name', 'section_str')
            )
        )

        property_type = self.get_enum(
            PropertyType, house_id, self.get_val(house, 'kind_name', 'kind_str'))

        generic_house = {
            'vendor': self.vendor,
            'vendor_house_id': house_id,
            'vendor_house_url': url,
            'imgs': [self.get_val(house, 'cover', 'img_src')],
            'top_region': top_region,
            'sub_region': sub_region,
            'property_type': property_type,
            'floor_ping': self.clean_number(house['area']),
            'floor': self.get_val(house, 'floor', clean_number=True),
            'total_floor': self.get_val(house, 'allfloor', clean_number=True),
            'monthly_price': self.get_val(house, 'price', clean_number=True)
        }

        # 99 and 100 are magic number in 591...
        # https://github.com/g0v/tw-rental-house-data/issues/11
        if generic_house['floor'] == 99:
            generic_house['floor'] = 0
        elif generic_house['floor'] == 100 and generic_house['total_floor']:
            generic_house['floor'] = generic_house['total_floor']+1

        empty_keys = []
        for key in generic_house:
            if generic_house[key] is None:
                empty_keys.append(key)

        for key in empty_keys:
            del generic_house[key]

        return generic_house

    def parse_list(self, response):
        data = json.loads(response.text)
        count = self.clean_number(data['records'])
        page = response.meta['seed']['page']

        if page == 0:
            cur_page = 1
            while cur_page * self.N_PAGE < count:
                self.gen_persist_request({
                    'region': response.meta['seed']['region'],
                    'page': cur_page
                })
                cur_page += 1

        houses = data['data']['topData'] + data['data']['data']

        for house in houses:
            house['is_vip'] = 'id' not in house
            yield RawHouseItem(
                house_id=house['post_id'],
                vendor=self.vendor,
                is_list=True,
                raw=json.dumps(house, ensure_ascii=False)
            )
            yield GenericHouseItem(**self.gen_shared_attrs(house, response.meta['seed']))

        yield True
