from scrapy.http import HtmlResponse

from scrapy_twrh.spiders.rental591.detail_raw_parser import get_coordinate_from_nuxt

from .conftest import DETAIL_URL, load_fixture

def detail_response():
    return HtmlResponse(
        url=DETAIL_URL,
        body=load_fixture('detail_591.html').encode('utf-8'),
        encoding='utf-8'
    )

def test_get_coordinate_from_nuxt():
    assert get_coordinate_from_nuxt(detail_response()) == '22.6100707,120.3052884'

def test_get_coordinate_from_page_without_nuxt():
    response = HtmlResponse(
        url=DETAIL_URL,
        body=b'<html><body>no script here</body></html>'
    )

    assert get_coordinate_from_nuxt(response) is None
