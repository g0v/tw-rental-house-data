from collections import namedtuple

SITE_URL = 'https://rent.591.com.tw'
LIST_ENDPOINT = '{}/home/search/rsList?is_new_list=1&type=1&kind=0&searchtype=1'.format(SITE_URL)
SESSION_ENDPOINT = '{}/?kind=0&region=6'.format(SITE_URL)

ListRequestMeta = namedtuple('ListRequestMeta', ['id', 'name', 'page'])

DetailRequestMeta = namedtuple('DetailRequestMeta', ['id', 'gps'])
