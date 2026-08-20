'''
Detail page parser for the 591 HTML served since the 2026 redesign, read from
the plain HTTP response. The date in the file name is when the pages behind
`tests/fixtures/20260820-*.html` were gathered.

591 renders the detail page on the server, so everything below is already in
the plain HTML. Two things are not in the DOM the way they used to be:

- the coordinate now only reaches `.google-maps-link` after the map is loaded
  by JS, so we read it out of the nuxt init script instead
- price / floor / area are plain text again, the `<wc-obfuscate-c-*>` images
  are gone, so no OCR here. Should 591 bring them back, this parser loses
  those fields quietly - the obfuscate-rate sentinel of the nightly probe is
  what is meant to catch that.

Older pages are parsed by detail_raw_parser_20251209, `detail_raw_parser`
picks between the two.
'''
import re
import urllib.parse as urlparse
from urllib.parse import parse_qs

from .util import SimpleNuxtInitParser, css

# 台澎金馬 rough bounded box - [21.811027, 118.350467] - [26.443459, 122.289387]
COORDINATE_PATTERN = r'(2\d\.\d+),(1[12]\d\.\d+)'

# 591 joins list-ish values with a full width comma, say 租金含 or 其他特色.
# The old template put each of them in its own <span>, keep that shape.
VALUE_SEPARATOR = '、'


def get_detail_raw_attrs(response):
    '''
    parse detail page HTML and find all fields in best effort
    keep original text, without any processing, so that we can re-parse it later

    TODO: photo list
    '''
    return {
        **get_title(response),
        **get_house_pattern(response),
        **get_house_price(response),
        **get_house_address(response),
        **get_service(response),
        **get_promotion(response),
        **get_description(response),
        **get_misc_info(response),
        **get_contact(response)
    }

def get_title(response):
    '''
    .title
    '''
    title = response.css('.title h1::text').get()

    return {
        'title': title,
        'deal_time': css(response, '.title .tag-deal', self_text=True),
        'breadcrumb': css(response, '.crumbs a.t5-link', self_text=True)
    }

def get_house_pattern(response):
    '''
    .house-label 新上架、可開伙、有陽台
    .pattern 物件類型、坪數、樓層/總樓層、建物類型
    '''
    tag_list = css(response, '.house-label > span', self_text=True)
    item_list = css(response, '.pattern > span:not(.line)', self_text=True)

    breadcrumb = css(response, '.crumbs a.t5-link', self_text=True)
    real_property_type = None
    if len(breadcrumb) >= 3:
        real_property_type = breadcrumb[2]

    # list of item_list per property_type
    # 車位 - floor_ping, 戶外廣場, 平面式, 最短租期
    # 整層住家 - x房x衛x廳, floor_ping, floor, building_type
    # else - <proper_type>, floor_ping, floor, building_type

    items = {}

    if real_property_type == '車位':
        items['property_type'] = '車位'
    else:
        if len(item_list) >= 1:
            items['property_type'] = item_list[0]
        if len(item_list) >= 4:
            items['floor_ping'] = item_list[1]
            items['floor'] = item_list[2]
            items['building_type'] = item_list[3]
        elif len(item_list) >= 2:
            items['building_type'] = item_list[1]

    return {
        'tags': tag_list,
        **items
    }

def get_house_price(response):
    '''
    .house-price 租金、押金
    押金 can be 押金*個月、押金面議，還可填其他（數值，不確定如何呈現）
    '''
    price_str = css(response, '.house-price .c-price .inline-flex-row', self_text=True)
    deposit_str = css(response, '.house-price', self_text=True)

    ret = {}

    if price_str:
        ret['price'] = price_str[0]
    if deposit_str:
        ret['deposit'] = deposit_str[0]

    return ret

def get_coordinate_from_nuxt(response):
    '''
    .google-maps-link only shows up after the map is loaded by JS, while the
    same coordinate is served in the nuxt init script of the plain HTML:
        positionRound: {..., address: cy, lat: cz, lng: cA, ...}
    '''
    for script in response.css('script::text').getall():
        if 'positionRound' not in script:
            continue

        positions = SimpleNuxtInitParser(script).get_component_arg_list(
            ['address', 'lat', 'lng']
        )

        for position in positions or []:
            lat = position.get('lat')
            lng = position.get('lng')
            if not lat or not lng:
                continue
            if re.fullmatch(COORDINATE_PATTERN, f'{lat},{lng}'):
                return f'{lat},{lng}'

    return None

def get_coordinate_from_gmap_link(response):
    '''
    .google-maps-link shows up once the map is loaded, say
    https://www.google.com/maps?f=q&hl=zh-TW&q=23.0413176,120.2412309&z=16
    '''
    gmap_url = response.css('.google-maps-link::attr("href")').get()

    if not gmap_url:
        return None

    query_params = parse_qs(urlparse.urlparse(gmap_url).query)

    for param in ['q', 'll']:
        if param not in query_params:
            continue

        coord_match = re.search(COORDINATE_PATTERN, query_params[param][0])
        if coord_match:
            return '{},{}'.format(coord_match.group(1), coord_match.group(2))

    return None

def get_house_address(response):
    '''
    約略經緯度、約略地址
    '''
    # TODO: support address, .address .load-map holds 中山區農安街

    # prefer the nuxt init script, as plain HTTP always carries it, while
    # .google-maps-link needs a rendered page. both give the same coordinate.
    rough_coordinate = get_coordinate_from_nuxt(response) \
        or get_coordinate_from_gmap_link(response)

    return {
        'rough_coordinate': rough_coordinate,
    }

def get_service(response):
    '''
    .service .desc-item 最短租期、身份要求、性別、可遷入日、養寵物、開伙
    .service .facility 提供設備/家具，dl.del is the one 591 crosses out

    591 used to group these under .service-cate titles, say 房屋守則, which is
    why the values live under a `service` key instead of the top level.
    '''
    service = {}
    for item in response.css('.service .desc-item'):
        label = css(item, '.desc-label', self_text=True)
        value = css(item, '.desc-value', self_text=True)
        if label and value:
            service[label[0]] = value[0]

    return {
        'service': service,
        'supported_facility': css(
            response, '.service .facility dl:not(.del) dd', self_text=True),
        'unsupported_facility': css(
            response, '.service .facility dl.del dd', self_text=True)
    }

def get_promotion(response):
    '''
    .preference-item 屋主直租、產權保障、etc..
    '''
    item_list = css(response, '.preference-item p:first-child', self_text=True)
    return {
        'promotion': item_list
    }

def get_description(response):
    '''
    .house-condition .house-condition-content .article 說明全文
    '''
    description = css(
        response,
        '.house-condition .house-condition-content .article',
        deep_text=True
    )

    return {
        'description': description
    }

def split_value(value):
    '''
    '水費、網路、第四台' -> ['水費', '網路', '第四台']
    '''
    return [token.strip() for token in value.split(VALUE_SEPARATOR) if token.strip()]

def get_misc_info(response):
    '''
    .house-detail-content 基礎資料（產權登記、法定用途、坪數、車位…）
                          與房屋價格（租金、押金、服務費、管理費、租金含…）

    Beware, .house-detail alone also matches a paragraph in the site footer,
    and each .value wraps its text in a span, next to icon spans which hold no
    text of their own.
    '''
    misc = {}
    for item in response.css('.house-detail-content .detail-section .item'):
        label = css(item, '.label', self_text=True)
        value = css(item, '.value span', self_text=True)
        if label and value:
            misc[label[0]] = split_value(value[0])

    return {
        'misc': misc
    }

def get_contact(response):
    '''
    .contact-card .contact 聯絡人
    .contact-card .phone
    '''
    contact_card = response.css('.contact-card')
    author_name = css(contact_card, '.name', self_text=True)
    agent_org = css(contact_card, '.econ-name', self_text=True)
    phone = css(contact_card, '.phone .contact-action-lg button span > span', self_text=True)

    if author_name:
        author_name = author_name[0]

    if agent_org:
        agent_org = agent_org[0]

    if phone:
        phone = phone[0]

    return {
        'author_name': author_name,
        'agent_org': agent_org,
        'author_phone': phone
    }
