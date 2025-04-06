import logging
import re
from scrapy_twrh.items import RawHouseItem
from .util import ListRequestMeta, DetailRequestMeta, css
from .request_generator import RequestGenerator

class ListMixin(RequestGenerator):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target_cities = []
        # Set to track houses we've already requested
        self.requested_houses = set()

    def default_start_list(self):
        for city in self.target_cities:
            yield self.gen_list_request(ListRequestMeta(
                city['id'],
                city['city'],
                0
            ))

    def default_parse_list(self, response):
        meta = response.meta['rental']

        page_items = css(response, '.paging li a::attr("href")')
        page_string = page_items[-1]
        page_match = re.search(r'page=(\d+)', page_string)
        if page_match:
            total_page = int(page_match.group(1))
        else:
            total_page = 1  # Default if no page number found

        logging.info('[list] crawl city:%s of %d/%d pages', meta.name, meta.page, total_page)

        if meta.page == 0:
            # generate all list request as now we know number of result
            cur_page = 1
            while cur_page < total_page:
                yield self.gen_list_request(ListRequestMeta(
                    meta.id,
                    meta.name,
                    cur_page
                ))
                cur_page += 1

        promotion_houses = self.gen_promotion_house(response)
        regular_houses = self.gen_regular_house(response)

        for house in promotion_houses + regular_houses:
            yield RawHouseItem(
                **house,
                is_list=True,
            )
            
            # Only generate detail request if we haven't seen this house before
            house_id = house['house_id']
            if house_id not in self.requested_houses:
                self.requested_houses.add(house_id)
                yield self.gen_detail_request(DetailRequestMeta(house_id))

    def gen_promotion_house(self, response):
        # .recommend-ware
        houses = []
        houses_resp = response.css('.recommend-ware')
        for house in houses_resp:
            url = house.css('a.title::attr("href")').get()
            house_id = url.split('/')[-1]
            houses.append({
                'vendor': self.vendor,
                'house_id': house_id,
                'raw': house.get()
            })

        return houses

    def gen_regular_house(self, response):
        # .item-info-title a::attr("href")
        houses = []
        houses_resp = response.css('.item')
        for house in houses_resp:
            url = house.css('.item-info-title a::attr("href")').get()
            house_id = url.split('/')[-1]
            houses.append({
                'vendor': self.vendor,
                'house_id': house_id,
                'raw': house.get()
            })

        return houses
