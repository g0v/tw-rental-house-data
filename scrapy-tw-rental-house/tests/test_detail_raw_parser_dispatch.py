'''Which dated parser each page goes to.

Crawling only ever meets today's template, but HouseEtc.detail_raw holds years
of pages in the one 591 served before its 2026 redesign, and
twrh-dataset/tools/rerun_detail_raw.py re-parses those.
'''
import sys

import pytest
from scrapy.http import HtmlResponse

from scrapy_twrh.spiders.rental591 import detail_raw_parser
from scrapy_twrh.spiders.rental591 import detail_raw_parser_20260820

from .conftest import load_fixture

# the containers the pre-2026 template had, and today's has not
LEGACY_PAGE = '''<html><body>
  <div class="title"><h1>老版式房源</h1></div>
  <div class="house-detail">
    <div class="content left">
      <div class="item"><div class="label">產權登記</div><div class="value">已辦理</div></div>
    </div>
  </div>
</body></html>'''

TODAY_FIXTURES = [
    '20260820-detail-whole-floor.html',
    '20260820-detail-suite-rooftop.html',
    '20260820-detail-shared-suite-owner.html',
    '20260820-detail-room-basement.html',
    '20260820-detail-room-female-only.html',
    '20260820-detail-room-plain-balcony.html',
    '20260820-detail-parking.html',
    '20260820-detail-not-found.html',
]


def response_of(fixture=None, body=None):
    if body is None:
        body = load_fixture(fixture)

    return HtmlResponse(
        url='https://rent.591.com.tw/10000001',
        body=body.encode('utf-8'),
        encoding='utf-8'
    )


@pytest.mark.parametrize('fixture', TODAY_FIXTURES)
def test_parse_a_page_591_serves_today_with_the_current_parser(fixture):
    picked = detail_raw_parser.pick_parser(response_of(fixture))

    assert picked is detail_raw_parser_20260820


def test_parse_a_pre_2026_page_with_the_frozen_parser():
    picked = detail_raw_parser.pick_parser(response_of(body=LEGACY_PAGE))

    assert picked.__name__.endswith('detail_raw_parser_20251209')
    assert picked.get_detail_raw_attrs(response_of(body=LEGACY_PAGE))['misc'] == {
        '產權登記': ['已辦理']
    }


def test_default_to_the_current_parser():
    '''
    a page with neither template's markers is far more likely to be 591
    changing again than an archived page
    '''
    picked = detail_raw_parser.pick_parser(
        response_of(body='<html><body><div class="error">?</div></body></html>'))

    assert picked is detail_raw_parser_20260820


def test_crawl_without_loading_paddleocr():
    '''
    only the frozen parser needs OCR, and importing it downloads models and
    costs hundreds of MB. A page 591 serves today must not reach it.
    '''
    assert 'paddleocr' not in sys.modules

    detail_raw_parser.get_detail_raw_attrs(
        response_of('20260820-detail-whole-floor.html'))

    assert 'paddleocr' not in sys.modules


@pytest.mark.parametrize('fixture', TODAY_FIXTURES)
def test_dispatch_to_the_same_result_as_the_parser_itself(fixture):
    response = response_of(fixture)

    assert detail_raw_parser.get_detail_raw_attrs(response) == \
        detail_raw_parser_20260820.get_detail_raw_attrs(response)
