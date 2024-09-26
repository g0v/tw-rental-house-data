import re
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

def reorder_inline_flex_dom(base: Response, selector):
    '''
    Issue #181, we may get innerHTML like <span> <i style="order:2;font-style:normal;">5</i></span>
    '''
    items = base.css(selector)
    ret = []
    for item in items:
        # child span may contain style="display:inline-flex;flex-direction:row-reverse;"
        i_list = item.css('span[style*=display\\:inline-flex] > i')
        plain_value = item.xpath('text()').get()
        if plain_value is not None:
            ret.append(plain_value)
        elif i_list:
            # check if it's reversed, find all values of flex-direction
            container_style = item.css('span[style*=display\\:inline-flex]::attr(style)').get()

            # we may have multiple flex-direction, get last one
            flex_directions = re.findall(r'flex-direction: ?([\w-]+)', container_style)
            order_base = 1
            if flex_directions:
                last_flex_direction = flex_directions[-1]
                if last_flex_direction == 'row-reverse':
                    order_base = -1
            # store i_list order (in style:order) and its ::text content)
            shuffled_list = []
            for i in i_list:
                order = i.css('::attr(style)').re_first(r'order:(\d+)')
                order = int(order) * order_base
                text = i.css('::text').get()
                shuffled_list.append((order, text))
            # sort by order
            shuffled_list.sort(key=lambda x: x[0])
            ret.append(''.join(map(lambda x: x[1], shuffled_list)))
    return ret

def css(base: Response, selector, default=None, deep_text=False, self_text=False):
    '''retrieve text in clean way'''
    if self_text:
        ret = reorder_inline_flex_dom(base, selector)
    elif deep_text:
        # Issue #30, we may get innerHTML like "some of <kkkk></kkkk>target <qqq></qqq>string"
        # deep_text=True retrieve text in the way different from ::text,
        # which will also get all child text.
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
