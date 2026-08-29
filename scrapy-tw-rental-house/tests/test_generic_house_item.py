'''raw dict -> GenericHouseItem, the half of the parser which normalizes.

591 renames its labels and rewords its values without warning, and every one
of those changes lands here: 產權登記 went from 已辦理 to 房屋已辦產權登記,
車位費 became 車位租金, and 房屋守則 turned from one paragraph into labelled
rows. A rename used to make a field disappear quietly, which is why each of
them has a test.
'''
import pytest
from decimal import Decimal

from scrapy_twrh.items import GenericHouseItem, RawHouseItem
from scrapy_twrh.spiders import enums

WHOLE_FLOOR = '20260820-detail-whole-floor.html'
SUITE_ROOFTOP = '20260820-detail-suite-rooftop.html'
SHARED_SUITE_OWNER = '20260820-detail-shared-suite-owner.html'
ROOM_BASEMENT = '20260820-detail-room-basement.html'
ROOM_FEMALE_ONLY = '20260820-detail-room-female-only.html'
PLAIN_BALCONY = '20260820-detail-room-plain-balcony.html'
PARKING = '20260820-detail-parking.html'
NOT_FOUND = '20260820-detail-not-found.html'

EVERY_HOUSE = [
    WHOLE_FLOOR, SUITE_ROOFTOP, SHARED_SUITE_OWNER,
    ROOM_BASEMENT, ROOM_FEMALE_ONLY, PLAIN_BALCONY,
]


@pytest.fixture
def house(spider, detail_response):
    def parse(fixture, status=200):
        items = list(spider.default_parse_detail(detail_response(fixture, status)))
        generic = [item for item in items if isinstance(item, GenericHouseItem)]
        assert len(generic) == 1
        return generic[0]

    return parse


@pytest.mark.parametrize('fixture', EVERY_HOUSE + [PARKING])
def test_parse_every_house_without_an_error(house, fixture):
    '''#204: a missing row used to raise TypeError and drop the whole house'''
    assert house(fixture)['deal_status'] == enums.DealStatusType.OPENED


def test_parse_a_whole_floor(house):
    whole_floor = house(WHOLE_FLOOR)

    assert whole_floor['top_region'] == enums.TopRegionType.台北市
    assert whole_floor['sub_region'] == enums.SubRegionType.台北市中山區
    assert whole_floor['property_type'] == enums.PropertyType.整層住家
    assert whole_floor['building_type'] == enums.BuildingType.電梯大樓
    assert whole_floor['monthly_price'] == 33999
    assert whole_floor['floor'] == 11
    assert whole_floor['total_floor'] == 14
    assert whole_floor['dist_to_highest_floor'] == 3
    assert whole_floor['is_rooftop'] is False
    assert whole_floor['floor_ping'] == 15.19
    assert whole_floor['n_bed_room'] == 1
    assert whole_floor['n_living_room'] == 1
    assert whole_floor['n_bath_room'] == 1
    assert whole_floor['n_balcony'] == 1


def test_parse_a_rooftop(house):
    rooftop = house(SUITE_ROOFTOP)

    assert rooftop['is_rooftop'] is True
    assert rooftop['total_floor'] == 4
    assert rooftop['floor'] == 5
    assert rooftop['property_type'] == enums.PropertyType.獨立套房
    assert rooftop['building_type'] == enums.BuildingType.公寓


def test_parse_a_basement(house):
    basement = house(ROOM_BASEMENT)

    assert basement['floor'] == -1
    assert basement['total_floor'] == 36
    assert basement['property_type'] == enums.PropertyType.雅房


def test_stop_at_the_property_type_for_a_parking_lot(house):
    parking = house(PARKING)

    assert parking['property_type'] == enums.PropertyType.車位
    assert parking['monthly_price'] == 2600
    # nothing else is meaningful for a parking lot, and 591 shows none of it
    assert 'floor' not in parking
    assert 'facilities' not in parking


def test_read_the_deposit(house):
    whole_floor = house(WHOLE_FLOOR)

    assert whole_floor['deposit_type'] == enums.DepositType.月
    assert whole_floor['n_month_deposit'] == 2
    assert whole_floor['deposit'] == 2 * 33999


def test_read_the_management_fee(house):
    '''591 writes it as 2,035元/月 under 管理費'''
    whole_floor = house(WHOLE_FLOOR)

    assert whole_floor['is_require_management_fee'] is True
    assert whole_floor['monthly_management_fee'] == 2035


def test_read_a_management_fee_which_the_rent_covers(house):
    '''管理費 listed under 租金含 means the tenant pays nothing on top'''
    basement = house(ROOM_BASEMENT)

    assert basement['is_require_management_fee'] is False
    assert basement['monthly_management_fee'] == 0


def test_read_the_parking_fee_under_its_new_label(house):
    '''車位費 in the old template, 車位租金 since 2026'''
    shared_suite = house(SHARED_SUITE_OWNER)

    assert shared_suite['has_parking'] is True
    assert shared_suite['is_require_parking_fee'] is True
    assert shared_suite['monthly_parking_fee'] == 0


def test_read_what_the_rent_covers(house):
    rooftop = house(SUITE_ROOFTOP)

    assert rooftop['additional_fee'] == {
        'eletricity': True,
        'water': False,
        'gas': False,
        'internet': False,
        'cable_tv': True,
    }


def test_read_the_property_registration(house):
    '''
    the row reads 房屋已辦產權登記 since 2026, it used to read 已辦理
    '''
    assert house(WHOLE_FLOOR)['has_perperty_registration'] is True


def test_read_the_house_rules(house):
    shared_suite = house(SHARED_SUITE_OWNER)

    assert shared_suite['can_cook'] is False
    assert shared_suite['allow_pet'] is False
    assert shared_suite['has_gender_restriction'] is False
    assert shared_suite['gender_restriction'] == enums.GenderType.不限
    # 學生、上班族 leaves 家庭 out
    assert shared_suite['has_tenant_restriction'] is True


def test_read_a_gender_restriction(house):
    female_only = house(ROOM_FEMALE_ONLY)

    assert female_only['has_gender_restriction'] is True
    assert female_only['gender_restriction'] == enums.GenderType.女
    assert female_only['can_cook'] is True


def test_read_no_tenant_restriction(house):
    '''學生、上班族、家庭 is everyone'''
    assert house(WHOLE_FLOOR)['has_tenant_restriction'] is False


def test_count_a_balcony_591_gives_no_count(house):
    '''
    a plain 陽台 among the provided facilities means one. Reading it as None
    used to break apt_feature_code and drop the house
    '''
    assert house(PLAIN_BALCONY)['n_balcony'] == 1
    assert house(WHOLE_FLOOR)['n_balcony'] == 1
    assert house(SHARED_SUITE_OWNER)['n_balcony'] == 0


def test_read_the_facilities(house):
    facilities = house(WHOLE_FLOOR)['facilities']

    assert facilities['冰箱'] is True
    assert facilities['第四台'] is False
    # 陽台 is counted separately, as n_balcony
    assert '1陽台' not in facilities


def test_read_the_coordinate(house):
    assert house(WHOLE_FLOOR)['rough_coordinate'] == [
        Decimal('25.0000000'), Decimal('121.5000000')
    ]


def test_leave_out_a_coordinate_591_does_not_publish(house):
    assert 'rough_coordinate' not in house(ROOM_FEMALE_ONLY)


def test_read_an_agency_contact(house):
    whole_floor = house(WHOLE_FLOOR)

    assert whole_floor['contact'] == enums.ContactType.房仲
    assert whole_floor['author'] == '0900000001'
    assert whole_floor['agent_org'] == '經紀業: 範例不動產有限公司'


def test_read_an_owner_contact(house):
    shared_suite = house(SHARED_SUITE_OWNER)

    assert shared_suite['contact'] == enums.ContactType.屋主
    assert shared_suite['author'] == '0900000003'
    assert 'agent_org' not in shared_suite


def test_report_a_house_591_no_longer_has(spider, detail_response):
    '''591 answers 404 with a page which is not a detail page at all'''
    items = list(spider.default_parse_detail(detail_response(NOT_FOUND, status=404)))

    assert [item['deal_status'] for item in items] == [
        enums.DealStatusType.NOT_FOUND
    ]


def test_report_a_house_whose_page_says_it_is_gone(spider, detail_response):
    '''and sometimes answers 200 with the same page'''
    items = list(spider.default_parse_detail(detail_response(NOT_FOUND)))
    generic = [item for item in items if isinstance(item, GenericHouseItem)]

    assert generic[0]['deal_status'] == enums.DealStatusType.NOT_FOUND


def test_keep_the_raw_html_and_dict(spider, detail_response):
    '''
    HouseEtc stores both, so that a parser fix can be re-run over the archive
    without crawling 591 again
    '''
    raw_html = None
    raw_dict = None

    for item in spider.default_parse_detail(detail_response(WHOLE_FLOOR)):
        if not isinstance(item, RawHouseItem):
            continue
        if 'raw' in item:
            raw_html = item['raw']
        if 'dict' in item:
            # gen_detail_shared_attrs keeps working on the very same dict
            raw_dict = dict(item['dict'])

    assert '<h1>' in raw_html
    assert raw_dict['price'] == '33,999'
    assert raw_dict['floor'] == '11F/14F'
    assert raw_dict['floor_ping'] == '15.19坪'


def test_short_breadcrumb_raises_for_retry(spider):
    '''
    2026-08-30: 591 transiently served six pages whose breadcrumb missed the
    region levels; the same pages were normal on the next batch. Raising keeps
    the request in the persist queue so a later batch retries, instead of
    storing a house without regions.
    '''
    from scrapy_twrh.spiders.rental591.detail_mixin import ShortBreadcrumbError

    with pytest.raises(ShortBreadcrumbError):
        spider.get_shared_basic({
            'house_id': 12345678,
            'breadcrumb': ['台北市'],
            'deal_time': None,
        })


def test_two_level_breadcrumb_falls_back_to_pattern_property_type(spider):
    '''regions readable, type missing -> take the one parsed from .pattern'''
    basic = spider.get_shared_basic({
        'house_id': 12345678,
        'breadcrumb': ['台北市', '中山區'],
        'property_type': '獨立套房',
        'deal_time': None,
        'supported_facility': [],
    })

    assert basic['top_region'] == enums.TopRegionType.台北市
    assert basic['sub_region'] == enums.SubRegionType.台北市中山區
    assert basic['property_type'] == enums.PropertyType.獨立套房
