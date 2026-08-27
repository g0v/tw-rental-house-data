'''List-page layout dispatch (list_mixin.default_parse_list).

The list page comes in four shapes, and telling them apart is what keeps the
persist queue honest: only pages the parser positively recognizes may finish
silently — anything else must raise, so the request stays behind as a leftover
and the error-rate breaker sees it.

- paging present            → the normal multi-page crawl
- `.empty` marker           → 591's empty-result page. Reached when the page
                              count shrank while the crawl was running and a
                              tail page generated at page 0 is now beyond the
                              last page (a daily occurrence in big cities).
- items but no paging       → a city small enough to fit one page
- none of the above         → UnknownListLayoutError
'''
import pytest
from scrapy import Request

from scrapy_twrh.items import RawHouseItem
from scrapy_twrh.spiders.rental591.list_mixin import UnknownListLayoutError

BEYOND_FIXTURE = '20260827-list-beyond-last-page.html'

# a synthetic single-page city: one item, no paging element. Only the
# selectors default_parse_list reads are present; everything is made up.
SINGLE_PAGE_BODY = (
    '<html><body><main>'
    '<div class="item"><div class="item-info-title">'
    '<a href="https://rent.591.com.tw/10000001">測試物件</a>'
    '</div></div>'
    '</main></body></html>'
)


def test_beyond_last_page_finishes_with_no_items(spider, list_response):
    response = list_response(BEYOND_FIXTURE, page=200)

    assert list(spider.default_parse_list(response)) == []


def test_unknown_layout_raises(spider, list_response):
    response = list_response(body='<html><body><div>maintenance</div></body></html>')

    with pytest.raises(UnknownListLayoutError):
        list(spider.default_parse_list(response))


def test_single_page_city_has_no_paging(spider, list_response):
    response = list_response(body=SINGLE_PAGE_BODY)

    yields = list(spider.default_parse_list(response))

    raw_items = [x for x in yields if isinstance(x, RawHouseItem)]
    requests = [x for x in yields if isinstance(x, Request)]
    assert len(raw_items) == 1
    # exactly the one detail request — no further list pages generated
    assert len(requests) == 1
    assert '10000001' in requests[0].url
