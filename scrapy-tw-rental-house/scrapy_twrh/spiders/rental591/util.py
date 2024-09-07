from collections import namedtuple
from scrapy.http import Response
from scrapy_twrh.spiders.util import clean_number

SITE_URL = 'https://rent.591.com.tw'
API_URL = 'https://bff-house.591.com.tw'
LIST_ENDPOINT = f'{API_URL}/v1/web/rent/list?'
DETAIL_ENDPOINT = f'{SITE_URL}/'
SESSION_ENDPOINT = '{}/?kind=0&region=6'.format(SITE_URL)

ListRequestMeta = namedtuple('ListRequestMeta', ['id', 'name', 'page'])

DetailRequestMeta = namedtuple('DetailRequestMeta', ['id'])

zh_number_dict = {
    '零': 0,
    '一': 1,
    '二': 2,
    '三': 3,
    '四': 4,
    '五': 5,
    '六': 6,
    '七': 7,
    '八': 8,
    '九': 9,
    '十': 10
}

def parse_price(number_string: str):
    '''
    #87, 社會住宅's monthly_price is a range
    '''
    tokens = number_string.split('~')
    price = clean_number(tokens[0])
    ret = { 'monthly_price':  price }
    if len(tokens) >= 2:
        ret['min_monthly_price'] = clean_number(tokens[1])

    return ret

def css(base: Response, selector, default=None, deep_text=False):
    '''
    Issue #30, we may get innerHTML like "some of <kkkk></kkkk>target <qqq></qqq>string"
    deep_text=True retrieve text in the way different from ::text,
    which will also get all child text.
    '''
    if deep_text:
        ret = map(lambda dom: ''.join(dom.css('*::text').getall()), base.css(selector))
    else:
        ret = base.css(selector).getall()
    if not ret:
        ret = [] if default is None else default

    ret = clean_string(ret)
    return list(ret)

def clean_string(strings):
    '''
    remove empty and strip
    '''
    strings = filter(lambda str: str.replace('\xa0', '').strip(), strings)
    strings = map(lambda str: str.replace('\xa0', '').strip(), strings)
    return strings

def from_zh_number(zh_number):
    '''
    一二三 -> 123
    '''
    if zh_number in zh_number_dict:
        return zh_number_dict[zh_number]
    else:
        raise Exception('ZH number {} not defined.'.format(zh_number))
