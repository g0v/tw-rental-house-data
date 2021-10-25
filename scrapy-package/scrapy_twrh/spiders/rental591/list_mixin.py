import json
from scrapy_twrh.items import RawHouseItem, GenericHouseItem
from scrapy_twrh.spiders.enums import PropertyType, TopRegionType, SubRegionType
from scrapy_twrh.spiders.util import clean_number
from .util import API_URL, ListRequestMeta, DetailRequestMeta, parse_price
from .request_generator import RequestGenerator

def get_list_val(house, regular_attr, top_attr=None, to_number=False):
    ret = None

    if regular_attr in house:
        ret = house[regular_attr]
    elif top_attr in house:
        ret = house[top_attr]

    if to_number and ret is not None:
        ret = clean_number(ret)

    return ret

class ListMixin(RequestGenerator):
    N_PAGE = 30

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target_cities = []

    def default_start_list(self):
        for city in self.target_cities:
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
            # generate all list request as now we know number of result
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
            house_item = self.gen_shared_attrs(house, meta)
            yield RawHouseItem(
                house_id=house_item['vendor_house_id'],
                vendor=self.vendor,
                is_list=True,
                raw=json.dumps(house, ensure_ascii=False)
            )
            yield GenericHouseItem(**house_item)
            yield self.gen_detail_request(DetailRequestMeta(house_item['vendor_house_id']))

    def gen_shared_attrs(self, house, meta: ListRequestMeta):
        house_id = get_list_val(house, 'id', 'post_id')

        url = "{}/v1/house/rent/detail?id={}".format(API_URL, house_id)

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

        property_type = None
        if 'kind_name' in house:
            self.get_enum(PropertyType, house_id, get_list_val(house, 'kind_name'))

        floor = None
        total_floor = None
        if 'floor_str' in house:
            floor_info = house['floor_str'].split('/')
            if len(floor_info) >= 2:
                floor = clean_number(floor_info[0])
                total_floor = clean_number(floor_info[1])

                if floor == '頂樓加蓋':
                    floor = total_floor +1
                elif 'B' in floor_info[0] and floor:
                    # basement
                    floor = -floor
                elif floor is None:
                    # 整棟
                    floor = 0

        price_range = parse_price(get_list_val(house, 'price'))

        generic_house = {
            'vendor': self.vendor,
            'vendor_house_id': house_id,
            'vendor_house_url': url,
            'imgs': get_list_val(house, 'photo_list'),
            'top_region': top_region,
            'sub_region': sub_region,
            'property_type': property_type,
            'floor_ping': clean_number(house['area']),
            'floor': floor,
            'total_floor': total_floor,
            **price_range
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
