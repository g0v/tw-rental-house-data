'''List-page layout dispatch and pagination (list_mixin.default_parse_list).

The list page comes in four shapes, and telling them apart is what keeps the
persist queue honest: only pages the parser positively recognizes may finish
silently — anything else must raise, so the request stays behind as a leftover
and the error-rate breaker sees it.

- paging present            → the normal multi-page crawl
- `.empty` marker           → 591's empty-result page: the trusted end-of-list
                              marker every city crawl finishes on (also shows
                              up mid-crawl when the page count shrank).
- items but no paging       → a city small enough to fit one page
- none of the above         → UnknownListLayoutError

Pagination does not trust the claimed total_page (promoted listings inflate
the real page count, pushing the oldest listings out of the claimed range):
the claimed range is fanned out as a lower bound, then any page with items
probes one page past the frontier until the empty page closes the city.
'''
import pytest
from scrapy import Request

from scrapy_twrh.items import RawHouseItem
from scrapy_twrh.spiders.rental591.list_mixin import UnknownListLayoutError
from scrapy_twrh.spiders.rental591.util import ListRequestMeta

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


def paged_body(claimed_total, house_id='10000001'):
    '''a synthetic list page claiming `claimed_total` pages, with one item'''
    return (
        '<html><body><main>'
        '<div class="paging"><li><a href="?page=2">2</a></li>'
        '<li><a href="?page={}">尾頁</a></li></div>'
        '<div class="item"><div class="item-info-title">'
        '<a href="https://rent.591.com.tw/{}">測試物件</a>'
        '</div></div>'
        '</main></body></html>'
    ).format(claimed_total, house_id)


def list_pages(yields):
    return [x.meta['rental'].page for x in yields
            if isinstance(x, Request)
            and isinstance(x.meta.get('rental'), ListRequestMeta)]


def test_beyond_last_page_finishes_with_no_items(spider, list_response):
    response = list_response(BEYOND_FIXTURE, page=200)

    assert list(spider.default_parse_list(response)) == []


def test_unknown_layout_raises(spider, list_response):
    response = list_response(body='<html><body><div>maintenance</div></body></html>')

    with pytest.raises(UnknownListLayoutError):
        list(spider.default_parse_list(response))


def test_single_page_city_probes_next_page(spider, list_response):
    response = list_response(body=SINGLE_PAGE_BODY)

    yields = list(spider.default_parse_list(response))

    raw_items = [x for x in yields if isinstance(x, RawHouseItem)]
    assert len(raw_items) == 1
    # one detail request, plus a probe of page 1 — even a "single page" city
    # only ends at the empty-result page
    detail_requests = [
        x for x in yields if isinstance(x, Request)
        and not isinstance(x.meta.get('rental'), ListRequestMeta)]
    assert len(detail_requests) == 1
    assert '10000001' in detail_requests[0].url
    assert list_pages(yields) == [1]


def test_page_zero_fans_out_claimed_range_without_probe(spider, list_response):
    response = list_response(body=paged_body(claimed_total=4))

    yields = list(spider.default_parse_list(response))

    # claimed 4 pages → fan out pages 1..3 (0-based); the probe waits until
    # the frontier page is actually parsed
    assert list_pages(yields) == [1, 2, 3]


def test_frontier_page_probes_past_claimed_total(spider, list_response):
    # page 0 first, so the fan-out registers pages 1..3 as generated
    list(spider.default_parse_list(list_response(body=paged_body(claimed_total=4))))

    # a mid page yields no new list request...
    mid_yields = list(spider.default_parse_list(
        list_response(body=paged_body(claimed_total=4, house_id='10000002'), page=1)))
    assert list_pages(mid_yields) == []

    # ...but the claimed last page keeps probing one page further
    frontier_yields = list(spider.default_parse_list(
        list_response(body=paged_body(claimed_total=4, house_id='10000003'), page=3)))
    assert list_pages(frontier_yields) == [4]

    beyond_yields = list(spider.default_parse_list(
        list_response(body=paged_body(claimed_total=4, house_id='10000004'), page=4)))
    assert list_pages(beyond_yields) == [5]


def test_probe_stops_at_hard_cap(spider, list_response):
    # runaway guard: if 591 kept serving items for any page number instead of
    # the empty-result page, the probe must stop at 2x claimed total + 5
    list(spider.default_parse_list(list_response(body=paged_body(claimed_total=2))))

    page = 1
    while page <= 20:
        yields = list(spider.default_parse_list(list_response(
            body=paged_body(claimed_total=2, house_id=str(10000001 + page)),
            page=page)))
        probes = list_pages(yields)
        if not probes:
            break
        assert probes == [page + 1]
        page += 1

    assert page == 2 * 2 + 5
