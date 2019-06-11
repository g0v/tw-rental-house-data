from scrapy import Request
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from scrapy_twrh.items import RawHouseItem, GenericHouseItem

class LocationOnlySpider(Rental591Spider):
    name = 'location-only'

    def __init__(self):
        self.count_per_city = {}
        super().__init__(
            parse_list=self.my_parse_list,
            parse_detail=self.my_parse_detail
        )

    def my_parse_list(self, response):
        for item in self.default_parse_list(response):
            # allow only detail request to speedup entire process
            if isinstance(item, Request):
                meta = item.meta['rental']
                if isinstance(meta, util.DetailRequestMeta):
                    yield item

    def my_parse_detail(self, response):
        for item in self.default_parse_detail(response):
            if isinstance(item, Request):
                # allow location page request
                yield item
            elif isinstance(item, GenericHouseItem):
                # ignore RawHouseItem
                # only yield item with rough_coordinate
                if 'rough_coordinate' in item and item['rough_coordinate'] is not None:
                    yield item
