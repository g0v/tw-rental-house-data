import json
from ..items import RawHouseItem, GenericHouseItem
from rental.enums import PropertyType, TopRegionType, SubRegionType
from .house_spider import HouseSpider
from .all_591_cities import all_591_cities


class List591Spider(HouseSpider):
    ENDPOINT = 'https://rent.591.com.tw/home/search/rsList?is_new_list=1&type=1&kind=0&searchtype=1'
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

    def gen_request_params(self, seed):
        city = seed['region']

        return {
            'url': "{}&region={}&firstRow={}".format(
                self.ENDPOINT,
                city['id'],
                seed['page'] * self.N_PAGE
            ),
            'headers': {'Cookie': 'urlJumpIp={};'.format(city['id'])},
            'priority': self.clean_number(city['id']),
            'meta': {'seed': seed}
        }

    def start_requests(self):
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

    def gen_shared_attrs(self, house):
        url = '{}/rent-detail-{}.html'.format(
            self.vendor.site_url, house['id'])

        top_region = self.get_enum(
            TopRegionType, house['id'], house['region_name'])

        sub_region = self.get_enum(
            SubRegionType,
            house['id'],
            '{}{}'.format(house['region_name'], house['section_name'])
        )

        property_type = self.get_enum(
            PropertyType, house['id'], house['kind_name'])

        return {
            'vendor': self.vendor,
            'vendor_house_id': house['id'],
            'vendor_house_url': url,
            'imgs': [house['cover']],
            'top_region': top_region,
            'sub_region': sub_region,
            'property_type': property_type,
            'floor_ping': self.clean_number(house['area']),
            'floor': self.clean_number(house['floor']),
            'total_floor': self.clean_number(house['allfloor']),
            'monthly_price': self.clean_number(house['price'])
        }

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

        for house in data['data']['topData']:
            house['is_vip'] = True
            yield RawHouseItem(
                house_id=house['post_id'],
                vendor=self.vendor,
                is_list=True,
                raw=json.dumps(house, ensure_ascii=False)
            )

        for house in data['data']['data']:
            house['is_vip'] = False
            yield RawHouseItem(
                house_id=house['id'],
                vendor=self.vendor,
                is_list=True,
                raw=json.dumps(house, ensure_ascii=False)
            )

            yield GenericHouseItem(**self.gen_shared_attrs(house))

        yield True
