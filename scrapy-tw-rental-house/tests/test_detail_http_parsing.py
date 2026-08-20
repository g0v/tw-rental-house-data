import sys
from copy import deepcopy
from decimal import Decimal

from scrapy_twrh.items import GenericHouseItem, RawHouseItem
from scrapy_twrh.spiders import enums

from .conftest import HOUSE_ID, load_fixture

def parse(spider, response):
    items = list(spider.default_parse_detail(response))
    generic = [item for item in items if isinstance(item, GenericHouseItem)]
    raw = [item for item in items if isinstance(item, RawHouseItem)]
    return generic, raw

def test_parse_house_from_plain_html(spider, detail_response):
    generic, raw = parse(spider, detail_response())

    assert len(generic) == 1
    house = generic[0]

    assert house['vendor_house_id'] == HOUSE_ID
    assert house['deal_status'] == enums.DealStatusType.OPENED
    assert house['monthly_price'] == 24000
    assert house['floor_ping'] == 19.81
    assert house['floor'] == 14
    assert house['total_floor'] == 15
    assert house['building_type'] == enums.BuildingType.電梯大樓
    assert house['n_bed_room'] == 2
    assert house['n_living_room'] == 1
    assert house['n_bath_room'] == 1
    assert raw

def test_parse_coordinate_from_plain_html(spider, detail_response):
    '''
    .google-maps-link needs a rendered page, the nuxt init script doesn't
    '''
    generic, _raw = parse(spider, detail_response())

    assert generic[0]['rough_coordinate'] == [
        Decimal('22.6100707'),
        Decimal('120.3052884')
    ]

def test_parse_prices_without_ocr(spider, detail_response):
    '''
    591 serves the numbers as plain text, the obfuscated images are gone
    '''
    fixture = load_fixture('detail_591.html')
    assert 'wc-obfuscate' not in fixture

    parse(spider, detail_response())

    assert 'paddleocr' not in sys.modules

def test_report_house_not_found(spider, detail_response):
    response = detail_response(fixture='detail_591_not_found.html', status=404)

    generic, _raw = parse(spider, response)

    assert len(generic) == 1
    assert generic[0]['deal_status'] == enums.DealStatusType.NOT_FOUND
    assert generic[0]['vendor_house_id'] == HOUSE_ID

def test_keep_raw_html_and_dict(spider, detail_response):
    raw_html = None
    raw_dict = None

    # take a copy while iterating, gen_detail_shared_attrs() keeps working on
    # the very same dict after RawHouseItem is yielded
    for item in spider.default_parse_detail(detail_response()):
        if not isinstance(item, RawHouseItem):
            continue
        if 'raw' in item:
            raw_html = item['raw']
        if 'dict' in item:
            raw_dict = deepcopy(item['dict'])

    assert '<h1' in raw_html
    assert raw_dict['title']
    assert raw_dict['price'] == '24,000'
    assert raw_dict['floor'] == '14F/15F'
    assert raw_dict['floor_ping'] == '19.81坪'
