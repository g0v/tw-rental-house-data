import pytest
import scrapy
from scrapy.http import HtmlResponse, Response

from .conftest import load_fixture

# a page which replies 200 without being a detail page, say when we get blocked
NO_HOUSE_PAGE = '<html><body><div class="error">please try again</div></body></html>'

def test_detail_request_goes_by_plain_http(spider, detail_request):
    request = detail_request()

    assert request.meta['twrh_detail'] is True
    assert 'playwright' not in request.meta

def test_playwright_meta_renders_the_page(spider):
    meta = spider.gen_playwright_meta()

    assert meta['playwright'] is True
    assert meta['playwright_page_init_callback'] == spider.playwright_utils.init_page
    assert len(meta['playwright_page_methods']) == 2

def test_keep_server_side_rendered_page(middleware, spider, detail_response, stats):
    response = detail_response()

    assert middleware.process_response(response.request, response, spider) is response
    assert stats.values == {}

@pytest.mark.parametrize('status', [301, 302, 404])
def test_keep_house_status_response(middleware, spider, detail_response, status):
    # 591 tells a house is gone or dealt by status code, no page to render
    response = detail_response(fixture='detail_591_not_found.html', status=status)

    assert middleware.process_response(response.request, response, spider) is response

def test_render_page_without_house(middleware, spider, detail_response, stats):
    response = detail_response(body=NO_HOUSE_PAGE)

    retry = middleware.process_response(response.request, response, spider)

    assert isinstance(retry, scrapy.Request)
    assert retry.meta['playwright'] is True
    assert retry.meta['twrh_playwright_fallback'] is True
    assert retry.url == response.request.url
    assert retry.dont_filter is True
    assert stats.values == {'twrh/playwright_fallback': 1}

def test_render_unexpected_status(middleware, spider, detail_response):
    # 403 is how 591 blocks us, the rendered page may still work
    response = detail_response(body=NO_HOUSE_PAGE, status=403)

    assert isinstance(
        middleware.process_response(response.request, response, spider),
        scrapy.Request
    )

def test_render_non_text_response(middleware, spider, detail_response):
    response = detail_response(body='', response_cls=Response)

    assert isinstance(
        middleware.process_response(response.request, response, spider),
        scrapy.Request
    )

def test_keep_meta_of_the_original_request(middleware, spider, detail_response):
    response = detail_response(body=NO_HOUSE_PAGE, db_request='the-queued-row')

    retry = middleware.process_response(response.request, response, spider)

    # twrh-dataset needs both of them to close the queued request
    assert retry.meta['db_request'] == 'the-queued-row'
    assert retry.meta['rental'] == response.request.meta['rental']

def test_dont_touch_meta_of_the_original_request(middleware, spider, detail_response):
    response = detail_response(body=NO_HOUSE_PAGE)

    middleware.process_response(response.request, response, spider)

    assert 'playwright' not in response.request.meta
    assert 'twrh_playwright_fallback' not in response.request.meta

def test_dont_render_twice(middleware, spider, detail_response):
    rendered = detail_response(body=NO_HOUSE_PAGE, twrh_playwright_fallback=True)
    assert middleware.process_response(
        rendered.request, rendered, spider) is rendered

    by_playwright = detail_response(body=NO_HOUSE_PAGE, playwright=True)
    assert middleware.process_response(
        by_playwright.request, by_playwright, spider) is by_playwright

def test_ignore_list_request(middleware, spider, list_request):
    request = list_request()
    response = HtmlResponse(
        url=request.url,
        request=request,
        body=NO_HOUSE_PAGE.encode('utf-8')
    )

    assert middleware.process_response(request, response, spider) is response

def test_ignore_spider_without_playwright(middleware, detail_response):
    class OtherSpider:
        pass

    response = detail_response(body=NO_HOUSE_PAGE)

    assert middleware.process_response(
        response.request, response, OtherSpider()) is response

def test_fallback_page_is_still_parsable(spider, detail_response):
    '''the middleware only re-sends the request, parsing stays the same'''
    response = detail_response(fixture='detail_591.html', twrh_playwright_fallback=True)

    items = list(spider.default_parse_detail(response))

    assert items
