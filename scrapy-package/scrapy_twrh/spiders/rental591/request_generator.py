from scrapy.spidermiddlewares.httperror import HttpError
from scrapy_twrh.spiders.rental_spider import RentalSpider
from .util import SITE_URL, API_URL, LIST_ENDPOINT, ListRequestMeta, DetailRequestMeta

class RequestGenerator(RentalSpider):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def gen_list_request_args(self, rental_meta: ListRequestMeta):
        # don't filter as 591 use 30x to indicate house status...
        ret = {
            'dont_filter': True,
            'errback': self.error_handler,
            'url': "{}&region={}&firstRow={}".format(
                LIST_ENDPOINT,
                rental_meta.id,
                rental_meta.page * self.N_PAGE
            ),
            'headers': {
                'Cookie': 'urlJumpIp={}; 591_new_session={}; PHPSESSID={}'.format(
                    rental_meta.id,
                    self.session['591_new_session'],
                    self.session['PHPSESSID']
                ),
                'X-CSRF-TOKEN': self.csrf_token
            }
        }
        return ret

    def gen_detail_request_args(self, rental_meta: DetailRequestMeta):
        if rental_meta.gps:
            # https://rent.591.com.tw/map-houseRound.html?type=1&detail=detail&version=1&post_id=6635655
            url = "{}/map-houseRound.html?type=1&detail=detail&version=1&post_id={}".format(
                SITE_URL, rental_meta.id)

            #19, the house may be closed in 3 hours when we found it....
            # retrieve gps in lowest priority
            # don't filter as 591 use 30x to indicate house status...
            return {
                'dont_filter': True,
                'url': url,
                'priority': -1,
                'errback': self.error_handler,
                'meta': {
                    'rental': rental_meta,
                    'handle_httpstatus_list': [404]
                }
            }
        else:
            # https://bff.591.com.tw/v1/house/rent/detail?id=11501075
            url = "{}/v1/house/rent/detail?id={}".format(API_URL, rental_meta.id)

            # don't filter as 591 use 30x to indicate house status...
            return {
                'dont_filter': True,
                'url': url,
                'errback': self.error_handler,
                'meta': {
                    'rental': rental_meta,
                    'handle_httpstatus_list': [400, 404, 302, 301]
                },
                'headers': {
                    'device': 'pc',
                    'deviceid': self.session['PHPSESSID']
                }
            }

    def error_handler(self, failure):
        if failure.check(HttpError):
            response = failure.value.response
            self.logger.error('HttpError on {}[{}]'.format(response.url, response.status))
        else:
            self.logger.error(
                'Error: {}'.format(failure))

