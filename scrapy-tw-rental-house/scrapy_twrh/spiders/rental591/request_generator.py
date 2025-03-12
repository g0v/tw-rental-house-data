from scrapy_playwright.page import PageMethod
from scrapy.spidermiddlewares.httperror import HttpError
from scrapy_twrh.spiders.rental_spider import RentalSpider
from scrapy.utils.project import get_project_settings

from .util import DETAIL_ENDPOINT, LIST_ENDPOINT, ListRequestMeta, DetailRequestMeta

class RequestGenerator(RentalSpider):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        settings = get_project_settings()
        self.browser_init_script = settings.get('BROWSER_INIT_SCRIPT', '')
        if not self.browser_init_script:
            self.logger.warning('BROWSER_INIT_SCRIPT not set in settings, some features may not work')

    def gen_list_request_args(self, rental_meta: ListRequestMeta):
        # don't filter as 591 use 30x to indicate house status...
        ret = {
            'dont_filter': True,
            'errback': self.error_handler,
            'url': "{}region={}&page={}".format(
                LIST_ENDPOINT,
                rental_meta.id,
                rental_meta.page + 1
            ),
            # 591 remove session check since #176, for some reason ╮(╯_╰)╭
            # 'headers': {
            #     'Cookie': 'urlJumpIp={}; 591_new_session={}; PHPSESSID={}'.format(
            #         rental_meta.id,
            #         self.session['591_new_session'],
            #         self.session['PHPSESSID']
            #     ),
            #     'X-CSRF-TOKEN': self.csrf_token
            # }
        }
        return ret
    
    async def enable_playwright(self, page, request):
        if self.browser_init_script:
            await page.add_init_script(self.browser_init_script)

    def gen_detail_request_args(self, rental_meta: DetailRequestMeta):
        # https://rent.591.com.tw/17122751
        url = "{}{}".format(DETAIL_ENDPOINT, rental_meta.id)

        # don't filter as 591 use 30x to indicate house status...
        return {
            'dont_filter': True,
            'url': url,
            'errback': self.error_handler,
            'meta': {
                'rental': rental_meta,
                'handle_httpstatus_list': [400, 404, 302, 301],
                'playwright': True,
                # 'playwright_include_page': True,
                'playwright_page_methods': [
                    PageMethod('wait_for_load_state', 'networkidle'),
                ],
                'playwright_page_init_callback': self.enable_playwright
            },
            # 591 remove session check since #176, for some reason ╮(╯_╰)╭
            # 'headers': {
            #     'device': 'pc',
            #     'deviceid': self.session['PHPSESSID']
            # }
        }

    def error_handler(self, failure):
        if failure.check(HttpError):
            response = failure.value.response
            self.logger.error('HttpError on {}[{}]'.format(response.url, response.status))
        else:
            self.logger.error(
                'Error: {}'.format(failure))

