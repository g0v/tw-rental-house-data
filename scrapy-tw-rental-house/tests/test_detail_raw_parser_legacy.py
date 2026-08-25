'''The parser refuses a page in a template it no longer supports.

Crawling only ever meets today's template, but HouseEtc.detail_raw holds years
of pages in the one 591 served before its 2026 redesign, and
twrh-dataset/tools/rerun_detail_raw.py re-parses those. A rerun over a
mixed-era archive must fail per old page instead of silently storing empty
fields — the parser for the old template lives in git history and released
packages, not in the tree.
'''
import pytest
from scrapy.http import HtmlResponse

from scrapy_twrh.spiders.rental591 import detail_raw_parser
from scrapy_twrh.spiders.rental591.detail_raw_parser import LegacyTemplateError

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

# price obfuscated as an image, the way 591 did before dropping it in 2026
OBFUSCATED_PAGE = '''<html><body>
  <div class="title"><h1>圖片混淆房源</h1></div>
  <wc-obfuscate-c-price data="data:image/png;base64,x"></wc-obfuscate-c-price>
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
def test_parse_a_page_591_serves_today(fixture):
    assert not detail_raw_parser.is_legacy_template(response_of(fixture))
    # and it parses without being refused
    detail_raw_parser.get_detail_raw_attrs(response_of(fixture))


@pytest.mark.parametrize('body', [LEGACY_PAGE, OBFUSCATED_PAGE])
def test_refuse_a_pre_2026_page_loudly(body):
    assert detail_raw_parser.is_legacy_template(response_of(body=body))

    with pytest.raises(LegacyTemplateError):
        detail_raw_parser.get_detail_raw_attrs(response_of(body=body))


def test_a_page_with_no_markers_is_parsed_as_today():
    '''
    a page carrying neither template's markers is far more likely to be 591
    changing again than an archived page, and today's parser is the one worth
    fixing then — so only a page which shows the old containers is refused
    '''
    response = response_of(body='<html><body><div class="error">?</div></body></html>')

    assert not detail_raw_parser.is_legacy_template(response)
    detail_raw_parser.get_detail_raw_attrs(response)
