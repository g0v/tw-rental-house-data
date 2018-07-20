import scrapy
import re
import traceback
from scrapy.spidermiddlewares.httperror import HttpError
from rental.models import HouseTS, Vendor
from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestType
from rental.enums import UNKNOWN_ENUM
from crawler.utils import now_tuple

# TODO: yield request


class HouseSpider(scrapy.Spider):
    queue_length = 30
    n_live_spider = 0

    def __init__(
        self,
        vendor,
        is_list,
        request_generator,
        response_parser,
        **kwargs
    ):
        '''
        request_gerator:
            parameter: accept seed as variable
            return: dictionary of request parameter

            errback, meta.db_request, dont_filter, callback
            will be added beforehand

        response_parser:
            Standard spider parser, don't need to handle request error and
            exception.
            Will be set as default request callback
        '''
        super().__init__(**kwargs)
        y, m, d, h = now_tuple()

        try:
            self.vendor = Vendor.objects.get(
                name = vendor
            )
        except Vendor.DoesNotExist:
            raise Exception('Vendor "{}" is not defined.'.format(vendor))

        if is_list:
            self.request_type = RequestType.LIST
        else:
            self.request_type = RequestType.DETAIL

        self.request_generator = request_generator
        self.response_parser = response_parser

        self.ts = {
            'y': y,
            'm': m,
            'd': d,
            'h': h
        }

    def has_request(self):
        undone_requests = RequestTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
            # Ignore pending request since we will generate new one and rerun it anyway
            is_pending = False,
            vendor = self.vendor,
            request_type = self.request_type
        )[:1]

        return undone_requests.count() > 0

    def has_record(self):
        today_houses = HouseTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h']
        )[:1]

        return today_houses.count() > 0

    def gen_persist_request(self, seed):
        RequestTS.objects.create(
            request_type=self.request_type,
            vendor=self.vendor,
            seed=seed
        )

    def next_request(self, request_generator=None):
        if self.n_live_spider >= self.queue_length:
            # At most self.queue_length in memory
            return None

        next_row = RequestTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
            vendor = self.vendor,
            request_type = self.request_type,
            is_pending = False
        ).order_by('created').first()

        if next_row is None:
            return None

        next_row.is_pending = True
        next_row.save()
        self.n_live_spider += 1

        requestArgs = {
            'dont_filter': True,
            'errback': self.error_handler,
            'callback': self.parser_wrapper,
            'meta': {}
        }

        if not request_generator:
            request_generator = self.request_generator

        requestArgs = {
            **requestArgs,
            **request_generator(next_row.seed)
        }

        if 'db_request' not in requestArgs['meta']:
            requestArgs['meta']['db_request'] = next_row

        return scrapy.Request(**requestArgs)

    def parser_wrapper(self, response):
        db_request = response.meta['db_request']
        db_request.last_status = response.status
        db_request.save()

        try:
            for item in self.response_parser(response):
                if item is True:
                    db_request.delete()
                else:
                    yield item
        except:
            self.logger.error(
                'Parser error in {} when handle meta {}. [{}] - {:.128}'.format(
                    self.name,
                    response.meta.get('seed', {}),
                    response.status,
                    response.text
                )
            )
            traceback.print_exc()

        self.n_live_spider -= 1
        while True:
            next_request = self.next_request()
            if next_request:
                yield next_request
            else:
                break

    def error_handler(self, failure):
        self.n_live_spider -= 1
        if failure.check(HttpError):
            response = failure.value.response
            self.logger.error('[Live|{}] HttpError on {}[{}]'.format(
                self.n_live_spider, response.url, response.status))

            request = failure.value.response.request.meta['db_request']
            request.last_status = response.status

            if response.status == 599:
                request.is_pending = False

            request.save()
        else:
            self.logger.error(
                '[Live|{}] Error: {}', self.n_live_spider, failure)

    def clean_number(self, number_string):
        if not number_string:
            return -1

        number_string = '{}'.format(number_string)
        pure_number = re.sub('[^\\d.-]', '', number_string)
        if not pure_number:
            # it could be '' is no digit included
            return ''
        elif pure_number.isdigit():
            return int(pure_number, base=10)
        else:
            return float(pure_number)

    def get_enum(self, EnumCls, house_id, value):
        try:
            enum = EnumCls[value]
        except AttributeError:
            self.logger.error('Unknown property: {}/{} in house {}'.format(
                value,
                EnumCls.__name__,
                house_id
            ))
            enum = UNKNOWN_ENUM

        return enum

    def css_first(self, base, selector, default=''):
        # Check how to find if there's missing attribute
        css = base.css(selector).extract_first() or default
        ret = ''
        if css:
            try:
                ret = next(self.clean_string([css]))
            except StopIteration:
                self.logger.info(
                    'Fail to get css first from {}({})'.format(
                        base,
                        selector
                    )
                )
        return ret

    def css(self, base, selector, default=[]):
        ret = base.css(selector).extract() or default
        ret = self.clean_string(ret)
        return list(ret)

    def clean_string(self, strings):
        # remove empty and strip
        strings = filter(lambda str: str.replace(u'\xa0', '').strip(), strings)
        strings = map(lambda str: str.replace(u'\xa0', '').strip(), strings)
        return strings
