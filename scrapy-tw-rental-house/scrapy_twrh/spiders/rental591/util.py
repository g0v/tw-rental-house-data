from collections import namedtuple
from scrapy_twrh.spiders.util import clean_number

SITE_URL = 'https://rent.591.com.tw'
API_URL = 'https://bff-house.591.com.tw'
LIST_ENDPOINT = '{}/v1/web/rent/list?'.format(API_URL)
SESSION_ENDPOINT = '{}/?kind=0&region=6'.format(SITE_URL)

ListRequestMeta = namedtuple('ListRequestMeta', ['id', 'name', 'page'])

DetailRequestMeta = namedtuple('DetailRequestMeta', ['id'])

def parse_price(number_string: str):
    #87, 社會住宅's monthly_price is a range
    tokens = number_string.split('~')
    price = clean_number(tokens[0])
    ret = { 'monthly_price':  price }
    if len(tokens) >= 2:
        ret['min_monthly_price'] = clean_number(tokens[1])

    return ret
