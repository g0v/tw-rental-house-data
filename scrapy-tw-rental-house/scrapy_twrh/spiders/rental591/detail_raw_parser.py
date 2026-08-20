import re
import logging
import urllib.parse as urlparse
from urllib.parse import parse_qs
from .ocr_utils import parse_floor, parse_ping, parse_price
from .util import SimpleNuxtInitParser, css


def parse_obfuscate_fields(response):
    '''
    Use OCR to parse obfuscated fields in the detail page
    '''
    ret = {}

    img_selectors = [
        { 'name': 'floor_ping', 'dom': 'wc-obfuscate-c-area', 'fn': parse_ping },
        { 'name': 'floor', 'dom': 'wc-obfuscate-c-floor', 'fn': parse_floor },
        { 'name': 'price', 'dom': 'wc-obfuscate-c-price', 'fn': parse_price },
        # { 'name': 'address', 'dom': 'wc-obfuscate-rent-map-address' }
    ]

    for selector in img_selectors:
        img = response.css(f'{selector["dom"]} + img::attr("src")').get()
        if not img:
            continue

        # output_path = os.path.join(os.getcwd(), 'ocr-test', selector['name'], house_id)
        # convert_base64_to_img(img, output_path)

        ret[selector['name']] = selector['fn'](img)

    return ret

def get_detail_raw_attrs(response):
    '''
    parse detail page HTML and find all fields in best effort
    keep original text, without any processing, so that we can re-parse it later

    TODO: photo list
    '''

    ret = {
        **get_title(response),
        **parse_obfuscate_fields(response),
        **get_house_pattern(response),
        **get_house_price(response),
        **get_house_address(response),
        **get_service(response),
        **get_promotion(response),
        **get_description(response),
        **get_misc_info(response),
        **get_contact(response)
    }

    return ret

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
    .house-pattern 物件類型、坪數、樓層/總樓層、建物類型
    '''
    tag_list = css(response, '.house-label > span', self_text=True)
    item_list = css(response, '.pattern > span:not(.line)', self_text=True)

    items = {}

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
        # skip floor_ping and floor as they are parsed separately
        if len(item_list) >= 4:
            # somehow floor_ping and floor are not obfuscated here
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

# 台澎金馬 rough bounded box - [21.811027, 118.350467] - [26.443459, 122.289387]
COORDINATE_PATTERN = r'(2\d\.\d+),(1[12]\d\.\d+)'

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
    .address 約略經緯度、約略地址
    '''
    # TODO: support address
    # address_str = css(response, '.address .load-map', self_text=True, default=['NA'])

    # prefer the nuxt init script, as it is served by plain HTTP as well, while
    # .google-maps-link needs a rendered page. both give the same coordinate.
    rough_coordinate = get_coordinate_from_nuxt(response)

    if not rough_coordinate:
        rough_coordinate = get_coordinate_from_gmap_link(response)

    return {
        'rough_coordinate': rough_coordinate,
        # 'rough_address': address_str[0]
    }

def get_service(response):
    '''
    .service .service-cate 租住說明、房屋守則、裝潢信息、etc
    '''
    services = {}
    cate_list = response.css('.service .service-cate > div')
    for cate in cate_list:
        title = css(cate, 'p', self_text=True)
        content = css(cate, 'span', self_text=True)
        if content and title:
            services[title[0]] = content[0]

    # .service .service-facility 提供設備
    supported_facility = css(response, '.service .service-facility dl:not(.del) dd', self_text=True)
    unsupported_facility = css(response, '.service .service-facility dl.del dd', self_text=True)
    services['supported_facility'] = supported_facility
    services['unsupported_facility'] = unsupported_facility
    return services

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
    description = css(response, '.house-condition .house-condition-content .article', deep_text=True)

    return {
        'description': description
    }

def get_misc_info(response):
    '''
    .house-detail .house-detail-content-left 租金含、押金、停車費
    .house-detail .house-detail-content-right  產權登記、法定用途、隔間材料
    '''
    misc = {}
    items = [
        *response.css('.house-detail .content.left .item'),
        *response.css('.house-detail .content.right .item')
    ]
    for item in items:
        title = css(item, '.label', self_text=True)
        content = css(item, '.value', self_text=True)
        if content and title:
            misc[title[0]] = content

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
