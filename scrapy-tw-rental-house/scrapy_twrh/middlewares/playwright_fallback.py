import logging

from scrapy.http import TextResponse

logger = logging.getLogger(__name__)

class PlaywrightFallbackMiddleware:
    '''
    Crawl detail pages with plain HTTP first, and re-send them through
    playwright only when the plain response is not usable.

    591 renders the detail page on the server, so the plain HTML already holds
    everything we parse. Rendering it in a browser costs a browser context, the
    whole JS bundle, and a networkidle wait per house, so we only pay it when
    we have to.

    This lives in a downloader middleware instead of the spider on purpose.
    Retrying inside parse_detail would break the persistent queue of
    twrh-dataset, which deletes the queued request as soon as the parser is
    done, and counts one response per queued request.
    '''

    # 591 tells house status by status code, no need to render those
    HOUSE_STATUS_CODES = [301, 302, 404]

    # a server side rendered page always has the house title
    SSR_INDICATOR = '.title h1'

    def __init__(self, stats):
        self.stats = stats

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.stats)

    def process_response(self, request, response, spider):
        if not self.should_fallback(request, response, spider):
            return response

        logger.info(
            'Plain HTTP gave us no page, retry %s with playwright [%s]',
            response.url,
            response.status
        )
        self.stats.inc_value('twrh/playwright_fallback')

        return request.replace(
            meta={
                **request.meta,
                **spider.gen_playwright_meta(),
                'twrh_playwright_fallback': True,
            },
            dont_filter=True
        )

    def should_fallback(self, request, response, spider):
        meta = request.meta

        if not meta.get('twrh_detail'):
            # list pages are plain HTTP only
            return False

        if meta.get('playwright') or meta.get('twrh_playwright_fallback'):
            # already rendered, don't loop
            return False

        if not hasattr(spider, 'gen_playwright_meta'):
            return False

        if response.status in self.HOUSE_STATUS_CODES:
            return False

        if not isinstance(response, TextResponse):
            return True

        return response.status != 200 or not response.css(self.SSR_INDICATOR)
