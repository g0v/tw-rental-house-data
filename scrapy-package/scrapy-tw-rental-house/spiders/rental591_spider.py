from collections import namedtuple
import json
import scrapy
from ..items import RawHouseItem, GenericHouseItem
from .rental_spider import RentalSpider
from .enums import PropertyType, TopRegionType, SubRegionType
from .all_591_cities import all_591_cities
from .util import clean_number

ListRequestMeta = namedtuple('ListRequestMeta', ['id', 'name', 'page'])

SITE_URL = 'https://rent.591.com.tw'
LIST_ENDPOINT = '{}/home/search/rsList?is_new_list=1&type=1&kind=0&searchtype=1'.format(SITE_URL)
SESSION_ENDPOINT = '{}/?kind=0&region=6'.format(SITE_URL)

def get_list_val(house, regular_attr, top_attr=None, to_number=False):
    ret = None

    if regular_attr in house:
        ret = house[regular_attr]
    elif top_attr in house:
        ret = house[top_attr]

    if to_number and ret is not None:
        ret = clean_number(ret)

    return ret

class Rental591Spider(RentalSpider):
    N_PAGE = 30

    def __init__(self, target_cities=None, **kwargs):
        super().__init__(
            vendor='591 租屋網',
            **kwargs
        )

        self.csrf_token = None
        self.session_token = None
        self.target_cities = []

        if target_cities:
            lookup_dict = {}
            for city in all_591_cities:
                lookup_dict[city['city']] = city
            for city in target_cities:
                if city in lookup_dict:
                    self.target_cities.append(lookup_dict[city])
        else:
            self.target_cities = all_591_cities

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

        for item in self.start_list():
            yield item

    def gen_list_request_args(self, rental_meta: ListRequestMeta):
        return {
            'url': "{}&region={}&firstRow={}".format(
                LIST_ENDPOINT,
                rental_meta.id,
                rental_meta.page * self.N_PAGE
            ),
            'headers': {
                'Cookie': 'urlJumpIp={}; 591_new_session={};'.format(
                    rental_meta.id,
                    self.session_token
                ),
                'X-CSRF-TOKEN': self.csrf_token
            }
        }

    def gen_detail_request_args(self, meta):
        pass

    def default_start_list(self):
        for city in self.target_cities:
            # let's do DFS
            yield self.gen_list_request(ListRequestMeta(
                city['id'],
                city['city'],
                0
            ))

    def default_parse_list(self, response):
        data = json.loads(response.text)
        count = clean_number(data['records'])
        meta = response.meta['rental']

        if meta.page == 0:
            cur_page = 1
            while cur_page * self.N_PAGE < count:
                yield self.gen_list_request(ListRequestMeta(
                    meta.id,
                    meta.name,
                    cur_page
                ))
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
            yield GenericHouseItem(**self.gen_shared_attrs(house, meta))

    def default_parse_detail(self, response):
        pass

    def gen_shared_attrs(self, house, meta: ListRequestMeta):
        house_id = get_list_val(house, 'id', 'post_id')

        url = '{}/rent-detail-{}.html'.format(SITE_URL, house_id)

        if 'region_name' in house:
            # topData doesn't contain region_name for some reason..
            top_region = self.get_enum(
                TopRegionType, house_id, house['region_name'])
        else:
            top_region = self.get_enum(
                TopRegionType, house_id, meta.name)

        sub_region = self.get_enum(
            SubRegionType,
            house_id,
            '{}{}'.format(
                TopRegionType(top_region).name,
                get_list_val(house, 'section_name', 'section_str')
            )
        )

        property_type = self.get_enum(
            PropertyType, house_id, get_list_val(house, 'kind_name', 'kind_str'))

        generic_house = {
            'vendor': self.vendor,
            'vendor_house_id': house_id,
            'vendor_house_url': url,
            'imgs': [get_list_val(house, 'cover', 'img_src')],
            'top_region': top_region,
            'sub_region': sub_region,
            'property_type': property_type,
            'floor_ping': clean_number(house['area']),
            'floor': get_list_val(house, 'floor', to_number=True),
            'total_floor': get_list_val(house, 'allfloor', to_number=True),
            'monthly_price': get_list_val(house, 'price', to_number=True)
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
