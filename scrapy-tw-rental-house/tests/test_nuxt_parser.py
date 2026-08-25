from scrapy_twrh.spiders.rental591.util import (
    SimpleNuxtInitParser,
    split_js_arguments,
    unquote_js_string,
)

def test_split_arguments_by_top_level_comma():
    assert split_js_arguments('a,b,1') == ['a', 'b', '1']

def test_keep_comma_inside_string():
    assert split_js_arguments('a,"12,345",b') == ['a', '"12,345"', 'b']
    assert split_js_arguments('"市中心,拎包入住,含車位",a') == [
        '"市中心,拎包入住,含車位"',
        'a'
    ]

def test_keep_comma_inside_bracket():
    assert split_js_arguments('a,[1,2],{b:1,c:2}') == ['a', '[1,2]', '{b:1,c:2}']

def test_keep_escaped_quote_inside_string():
    assert split_js_arguments(r'"say \"hi\", now",a') == [r'"say \"hi\", now"', 'a']

def test_unquote_string():
    assert unquote_js_string('"元\\u002F月"') == '元/月'
    assert unquote_js_string("'a'") == 'a'
    assert unquote_js_string(' 12 ') == '12'
    assert unquote_js_string('void 0') == 'void 0'

def test_map_arguments_to_values():
    parser = SimpleNuxtInitParser(
        'window.__NUXT__=(function(a,b,c){return {x:a}}("first","second","third"))'
    )

    assert parser.dict == {'a': 'first', 'b': 'second', 'c': 'third'}

def test_map_arguments_to_values_holding_comma():
    '''
    the bug this test guards: splitting the argument list by every comma
    pushes all the following values one slot forward, so that every argument
    reads a value of its neighbor
    '''
    parser = SimpleNuxtInitParser(
        'window.__NUXT__=(function(a,b,c){return {x:a}}'
        '("12,345","市中心,拎包入住,含車位","third"))'
    )

    assert parser.dict == {
        'a': '12,345',
        'b': '市中心,拎包入住,含車位',
        'c': 'third'
    }

def test_read_component_arguments():
    parser = SimpleNuxtInitParser(
        'window.__NUXT__=(function(a,b,c){'
        'return {positionRound:{address:a,lat:b,lng:c}}'
        '}("前鎮區中山二路","22.6100707","120.3052884"))'
    )

    assert parser.get_component_arg_list(['address', 'lat', 'lng']) == [{
        'address': '前鎮區中山二路',
        'lat': '22.6100707',
        'lng': '120.3052884'
    }]

def test_keep_comma_inside_inline_style():
    '''
    the 屋況介紹 of a house carries inline style, say the house 21788398 whose
    description holds `rgb(20, 106, 153)`. Both the commas of the color and
    the ones of the sentences live in the same value.
    '''
    parser = SimpleNuxtInitParser(
        'window.__NUXT__=(function(a,b){return {x:a}}'
        '("<p style=\\"color: rgb(20, 106, 153)\\">近捷運,近商圈</p>","22.6100707"))'
    )

    assert parser.dict == {
        'a': '<p style="color: rgb(20, 106, 153)">近捷運,近商圈</p>',
        'b': '22.6100707'
    }
