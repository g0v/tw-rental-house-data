import re
from .util import css, clean_number

def get_detail_raw_attrs(response):
    '''
    parse detail page HTML and find all fields in best effort
    keep original text, without any processing, so that we can re-parse it later

    TODO: photo list

    To check:
    - has_parking, is_require_parking_fee, monthly_management_fee, is_require_management_fee: https://rent.591.com.tw/17143085
    deal_status,
    is_rooftop, 
    no additional_fee, living_functions, transportation
    has_perperty_registration
    '''
    ret = {
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

    return ret

def get_title(response):
    '''
    .house-title title
    '''
    return {
        'title': css(response, '.house-title h1::text')[0],
        'deal_time': css(response, '.house-title .tag-deal::text'),
        'breadcrumb': css(response, '.crumbs a.t5-link::text')
    }

def get_house_pattern(response):
    '''
    .house-pattern 物件類型、坪數、樓層/總樓層、建物類型
    '''
    item_list = css(response, '.house-pattern span::text')
    items = {}
    fields_def = ['property_type', 'floor_ping', 'floor', 'building_type']

    for i, field in enumerate(fields_def):
        value = item_list[i]
        if len(item_list) > i:
            items[field] = value

    return items

def get_house_price(response):
    '''
    .house-price 租金、押金
    押金 can be 押金*個月、押金面議，還可填其他（數值，不確定如何呈現）
    '''
    price = css(response, '.house-price .price strong::text')
    deposit_str = css(response, '.house-price::text')

    return {
        'price': price[0],
        'deposit': deposit_str[0]
    }

def get_house_address(response):
    '''
    .address 約略經緯度、約略地址
    '''
    address_str = css(response, '.address .load-map::text')

    # lat lng is in NUXT init script
    js_scripts = css(response, 'script::text')
    nuxt_script = next(filter(lambda script: '__NUXT__' in script, js_scripts), None)

    # 台澎金馬 rough bounded box - [21.811027, 118.350467] - [26.443459, 122.289387]
    # in nuxt_script, find first pattern that match regex 2\d\.\d{7}, 1[12]\d\.\d{7}
    latlng_match = re.search(r"(2\d\.\d{7},1[12]\d\.\d{7})", nuxt_script)
    rough_coordinate = None
    if latlng_match:
        rough_coordinate = latlng_match.group(1)

    return {
        'rough_coordinate': rough_coordinate,
        'rough_address': address_str[0]
    }

def get_service(response):
    '''
    .service .service-cate 租住說明、房屋守則、裝潢信息、etc
    '''
    services = {}
    cate_list = response.css('.service .service-cate > div')
    for cate in cate_list:
        title = css(cate, 'p::text')[0]
        content = css(cate, 'span::text')
        if content and title:
            services[title] = content[0]

    # .service .service-facility 提供設備
    supported_facility = css(response, '.service .service-facility dl:not(.del) dd::text')
    unsupported_facility = css(response, '.service .service-facility dl.del dd::text')
    services['supported_facility'] = supported_facility
    services['unsupported_facility'] = unsupported_facility
    return services

def get_promotion(response):
    '''
    .preference-item 屋主直租、產權保障、etc..
    '''
    item_list = css(response, '.preference-item p:first-child::text')
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
    .house-detail .house-detail-content-left 租金、押金、停車費
    .house-detail .house-detail-content-right  產權登記、法定用途、隔間材料
    '''
    misc = {}
    items = [
        *response.css('.house-detail .content.left .item'),
        *response.css('.house-detail .content.right .item')
    ]
    for item in items:
        title = css(item, '.label::text')[0]
        content = css(item, '.value::text')
        if content and title:
            misc[title] = content[0]

    return {
        'misc': misc
    }

def get_contact(response):
    '''
    .contact-card .contact 聯絡人
    .contact-card .phone
    '''
    contact_card = response.css('.contact-card')
    author_name = css(contact_card, '.name::text')
    agent_org = css(contact_card, '.econ-name::text')
    phone = css(contact_card, '.phone button span > span::text')

    if author_name:
        author_name = author_name[0]

    if agent_org:
        agent_org = agent_org[0]

    if phone:
        phone = phone[0]

    return {
        'author_name': author_name,
        'agent_org': agent_org,
        'phone': phone
    }
