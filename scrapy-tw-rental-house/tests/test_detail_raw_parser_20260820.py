'''HTML -> raw dict, on the template 591 serves today.

One test per thing the parser has to get right, and the fixtures between them
cover the branches which behave differently: 車位 against every other property
type, an owner against an agency, a rooftop and a basement floor, a house 591
publishes no coordinate for.
'''
import pytest
from scrapy.http import HtmlResponse

from scrapy_twrh.spiders.rental591 import detail_raw_parser_20260820 as parser

from .conftest import load_fixture

WHOLE_FLOOR = '20260820-detail-whole-floor.html'
SUITE_ROOFTOP = '20260820-detail-suite-rooftop.html'
SHARED_SUITE_OWNER = '20260820-detail-shared-suite-owner.html'
ROOM_BASEMENT = '20260820-detail-room-basement.html'
ROOM_FEMALE_ONLY = '20260820-detail-room-female-only.html'
PLAIN_BALCONY = '20260820-detail-room-plain-balcony.html'
PARKING = '20260820-detail-parking.html'

EVERY_HOUSE = [
    WHOLE_FLOOR, SUITE_ROOFTOP, SHARED_SUITE_OWNER,
    ROOM_BASEMENT, ROOM_FEMALE_ONLY, PLAIN_BALCONY,
]


def parse(fixture):
    response = HtmlResponse(
        url='https://rent.591.com.tw/10000001',
        body=load_fixture(fixture).encode('utf-8'),
        encoding='utf-8'
    )
    return parser.get_detail_raw_attrs(response)


@pytest.mark.parametrize('fixture', EVERY_HOUSE + [PARKING])
def test_read_the_breadcrumb(fixture):
    top_region, sub_region, property_type = parse(fixture)['breadcrumb']

    assert top_region.endswith(('市', '縣'))
    assert sub_region.endswith(('區', '鄉', '鎮', '市'))
    assert property_type


def test_read_a_whole_floor():
    house = parse(WHOLE_FLOOR)

    assert house['breadcrumb'] == ['台北市', '中山區', '整層住家']
    # 整層住家 shows the room pattern where other types show their own name
    assert house['property_type'] == '1房1廳1衛'
    assert house['floor_ping'] == '15.19坪'
    assert house['floor'] == '11F/14F'
    assert house['building_type'] == '電梯大樓'
    assert house['price'] == '33,999'
    assert house['deposit'] == '二個月'
    assert house['deal_time'] == []


def test_read_a_rooftop_suite():
    house = parse(SUITE_ROOFTOP)

    assert house['property_type'] == '獨立套房'
    assert house['floor'] == '頂層加蓋/4F'
    assert house['building_type'] == '公寓'


def test_read_a_basement_room():
    house = parse(ROOM_BASEMENT)

    assert house['property_type'] == '雅房'
    assert house['floor'] == 'B1/36F'


def test_read_a_parking_lot():
    '''
    591 gives a parking lot neither 房屋詳情 nor 租住與設備, and its .pattern
    starts with the area instead of the property type
    '''
    parking = parse(PARKING)

    assert parking['property_type'] == '車位'
    assert parking['price'] == '2,600'
    assert 'floor' not in parking
    assert 'floor_ping' not in parking
    assert parking['misc'] == {}
    assert parking['service'] == {}
    assert parking['supported_facility'] == []


@pytest.mark.parametrize('fixture', EVERY_HOUSE)
def test_read_the_basic_and_price_rows(fixture):
    misc = parse(fixture)['misc']

    assert misc['產權登記'] == ['房屋已辦產權登記']
    assert misc['押金'] == ['二個月']
    assert misc['租金'][0].endswith('元/月') or '元/月' in misc['租金'][0]


def test_split_a_comma_joined_row():
    '''591 joins 租金含 with a full width comma, one entry per value'''
    misc = parse(SUITE_ROOFTOP)['misc']

    assert misc['租金含'] == ['水費', '網路', '瓦斯費', '清潔費']
    assert misc['管理費'] == ['501元/月']


def test_read_the_parking_fee_under_its_new_label():
    misc = parse(SHARED_SUITE_OWNER)['misc']

    assert misc['車位租金'] == ['費用另計']
    assert misc['車位'] == ['平面式']


def test_skip_the_tooltip_next_to_a_value():
    '''
    法定用途 and 建物面積 carry a tooltip icon inside .value, which must not
    end up in the value
    '''
    misc = parse(WHOLE_FLOOR)['misc']

    assert misc['法定用途'] == ['商業用']
    assert misc['建物面積'] == ['7.66坪 (不含公設)']


def test_read_the_house_rules():
    service = parse(SHARED_SUITE_OWNER)['service']

    assert service['養寵物'] == '不可養寵物'
    assert service['開伙'] == '不可開伙'
    assert service['性別'] == '此房屋男女皆可租住'
    assert service['身份要求'] == '學生、上班族'


def test_read_a_gender_restriction():
    assert parse(ROOM_FEMALE_ONLY)['service']['性別'] == '此房屋限女生租住'


def test_read_a_balcony_591_gives_no_count():
    '''most houses get 1陽台, some just 陽台'''
    assert '陽台' in parse(PLAIN_BALCONY)['supported_facility']
    assert '1陽台' in parse(WHOLE_FLOOR)['supported_facility']


def test_tell_crossed_out_facility_from_provided_one():
    house = parse(WHOLE_FLOOR)

    assert '冰箱' in house['supported_facility']
    assert '1陽台' in house['supported_facility']
    assert '第四台' in house['unsupported_facility']
    assert '車位' in house['unsupported_facility']
    assert not set(house['supported_facility']) & set(house['unsupported_facility'])


@pytest.mark.parametrize('fixture', EVERY_HOUSE + [PARKING])
def test_read_the_contact(fixture):
    house = parse(fixture)

    role, _, name = house['author_name'].partition(': ')
    assert role in ['屋主', '仲介', '代理人']
    assert name
    assert house['author_phone'].startswith('0900-000-')


def test_read_the_agency_only_when_there_is_one():
    assert parse(WHOLE_FLOOR)['agent_org'] == '經紀業: 範例不動產有限公司'
    # 591 shows no 經紀業 row for a house the owner rents out
    assert parse(SHARED_SUITE_OWNER)['agent_org'] == []


@pytest.mark.parametrize('fixture', EVERY_HOUSE + [PARKING])
def test_read_the_description_across_nested_tags(fixture):
    description = parse(fixture)['description']

    assert len(description) == 1
    # 屋況介紹 is rich text, deep_text has to walk into <strong> and past <br>
    assert '合成的屋況介紹' in description[0]
    assert description[0].endswith('。')


def test_read_the_promotion():
    assert parse(WHOLE_FLOOR)['promotion'] == ['產權有保障', '拎包入住', '7日上新']
    # 591 gives no 優選理由 to every house
    assert parse(ROOM_BASEMENT)['promotion'] == []


def test_read_the_tags():
    assert parse(SHARED_SUITE_OWNER)['tags'] == [
        '屋主直租', '近捷運', '新上架', '拎包入住', '隨時可遷入'
    ]


def test_parse_a_page_which_is_not_a_detail_page():
    '''nothing found is fine, detail_mixin decides what to do with that'''
    house = parse('20260820-detail-not-found.html')

    assert house['title'] is None
    assert house['breadcrumb'] == []
    assert house['misc'] == {}
