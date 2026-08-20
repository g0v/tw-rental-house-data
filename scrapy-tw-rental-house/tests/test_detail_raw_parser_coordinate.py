'''The coordinate, which is the one field that does not live in the DOM.

591 only fills .google-maps-link once the map is loaded by JS, so plain HTTP
has to read the nuxt init script instead. The script is minified into an
argument list, and any value holding a comma - an inline style with
`rgb(20, 106, 153)`, a thousands separator, a comma joined list - used to
shift every following value by one and land lat / lng on something else.
'''
import pytest
from scrapy.http import HtmlResponse

from scrapy_twrh.spiders.rental591.detail_raw_parser_20260820 import (
    get_coordinate_from_gmap_link,
    get_coordinate_from_nuxt,
)
from scrapy_twrh.spiders.rental591.util import (
    SimpleNuxtInitParser,
    split_js_arguments,
    unquote_js_string,
)

from .conftest import load_fixture


def response_of(fixture=None, body=None):
    if body is None:
        body = load_fixture(fixture)

    return HtmlResponse(
        url='https://rent.591.com.tw/10000001',
        body=body.encode('utf-8'),
        encoding='utf-8'
    )


@pytest.mark.parametrize('fixture,coordinate', [
    ('20260820-detail-whole-floor.html', '25.0000000,121.5000000'),
    ('20260820-detail-suite-rooftop.html', '24.1000000,120.6000000'),
    ('20260820-detail-shared-suite-owner.html', '23.0000000,120.2000000'),
    ('20260820-detail-room-basement.html', '25.1000000,121.7000000'),
    ('20260820-detail-room-plain-balcony.html', '24.8000000,121.0000000'),
    ('20260820-detail-parking.html', '22.6000000,120.3000000'),
])
def test_read_the_coordinate_out_of_the_nuxt_script(fixture, coordinate):
    assert get_coordinate_from_nuxt(response_of(fixture)) == coordinate


def test_report_no_coordinate_when_591_publishes_none():
    '''591 answers lat: 0, lng: 0 for some houses'''
    response = response_of('20260820-detail-room-female-only.html')

    assert get_coordinate_from_nuxt(response) is None


def test_report_no_coordinate_without_a_nuxt_script():
    assert get_coordinate_from_nuxt(
        response_of(body='<html><body>no script here</body></html>')) is None


def test_read_the_coordinate_out_of_a_rendered_map_link():
    '''kept for pages which were crawled through a browser'''
    response = response_of(body=(
        '<html><body><a class="google-maps-link" '
        'href="https://www.google.com/maps?f=q&hl=zh-TW&q=23.0413176,120.2412309&z=16">'
        '地圖</a></body></html>'
    ))

    assert get_coordinate_from_gmap_link(response) == '23.0413176,120.2412309'


def test_ignore_a_coordinate_outside_taiwan():
    response = response_of(body=(
        '<html><body><a class="google-maps-link" '
        'href="https://www.google.com/maps?q=48.8584,2.2945"></a></body></html>'
    ))

    assert get_coordinate_from_gmap_link(response) is None


@pytest.mark.parametrize('arguments,expected', [
    ('a,b,c', ['a', 'b', 'c']),
    ('a,"b,c",d', ['a', '"b,c"', 'd']),
    ('a,[1,2],{x:1,y:2}', ['a', '[1,2]', '{x:1,y:2}']),
    ('"a\\"b,c",d', ['"a\\"b,c"', 'd']),
    ('"rgb(20, 106, 153)",1', ['"rgb(20, 106, 153)"', '1']),
])
def test_split_by_top_level_comma_only(arguments, expected):
    assert split_js_arguments(arguments) == expected


@pytest.mark.parametrize('raw,expected', [
    ('"元\\u002F月"', '元/月'),
    ('12', '12'),
    ('25.0628632', '25.0628632'),
    ('"12,345"', '12,345'),
    ('true', 'true'),
])
def test_unquote_a_value(raw, expected):
    assert unquote_js_string(raw) == expected


def test_keep_every_value_in_place_despite_commas():
    '''
    the regression itself: the values before lat / lng all hold commas, and
    a naive split would hand lat the value meant for the one before it
    '''
    script = (
        'window.__NUXT__=(function(a,b,c,d,e){return {x:{price:a,tags:b,'
        'positionRound:{address:c,lat:d,lng:e}}}}'
        '("12,345","近捷運,新上架","中正區範例路",25.0000000,121.5000000))'
    )

    nuxt = SimpleNuxtInitParser(script)

    assert nuxt.dict['a'] == '12,345'
    assert nuxt.dict['b'] == '近捷運,新上架'
    assert nuxt.get_component_arg_list(['address', 'lat', 'lng']) == [
        {'address': '中正區範例路', 'lat': '25.0000000', 'lng': '121.5000000'}
    ]
