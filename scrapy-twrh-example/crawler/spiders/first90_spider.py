from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from scrapy import Request

GOAL_PER_CITY = 90

class First90Spider(Rental591Spider):
    """
    We use page number to estimate total number of house for simpilicity.
    The actual house crawled will be more than 90/city as 591 provide additional house for advertisment.
    """
    name = 'first90'

    def __init__(self):
        self.count_per_city = {}

        super().__init__(parse_list=self.my_parse_list)

    def is_request_too_much(self, request):
        meta = request.meta['rental']
        if not isinstance(meta, util.ListRequestMeta):
            return False

        if meta.name not in self.count_per_city:
            # we already got page 0 for each city
            self.count_per_city[meta.name] = self.N_PAGE

        if self.count_per_city[meta.name] < GOAL_PER_CITY:
            self.count_per_city[meta.name] += self.N_PAGE
            return False

        self.logger.info('Too much request for {}/#{}'.format(meta.name, meta.page))
        return True

    def my_parse_list(self, response):
        for item in self.default_parse_list(response):
            if not isinstance(item, Request):
                yield item
            elif not self.is_request_too_much(item):
                yield item
