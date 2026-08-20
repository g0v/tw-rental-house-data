import os
import socket
from types import SimpleNamespace

import pytest
import scrapy
from scrapy.http import HtmlResponse

from scrapy_twrh.middlewares import PlaywrightFallbackMiddleware
from scrapy_twrh.spiders.rental591 import Rental591Spider
from scrapy_twrh.spiders.rental591.util import DetailRequestMeta, ListRequestMeta

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

# the house of detail_591.html, its contact person is replaced by a fake one
HOUSE_ID = '21828598'

# only a label of the saved HTML, no test ever requests it
DETAIL_URL = f'https://rent.591.com.tw/{HOUSE_ID}'

def load_fixture(name):
    with open(os.path.join(FIXTURE_DIR, name), encoding='utf-8') as fixture:
        return fixture.read()

class FakeStats:
    '''enough of a stats collector to keep the middleware happy'''
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, **kwargs):
        self.values[key] = self.values.get(key, 0) + count

@pytest.fixture(autouse=True)
def in_tmp_cwd(tmp_path, monkeypatch):
    '''keep the caches created on spider startup out of the repository'''
    monkeypatch.chdir(tmp_path)

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    '''
    Every test reads HTML from tests/fixtures, so that they keep working
    after the houses are gone from 591. Crawling for real is a bug here,
    fail loudly instead of hitting 591 by accident.
    '''
    def blocked(*_args, **_kwargs):
        raise RuntimeError('tests must not crawl, please add a fixture instead')

    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)

@pytest.fixture
def spider():
    return Rental591Spider(target_cities=['金門縣'])

@pytest.fixture
def stats():
    return FakeStats()

@pytest.fixture
def middleware(stats):
    return PlaywrightFallbackMiddleware.from_crawler(SimpleNamespace(stats=stats))

@pytest.fixture
def detail_request(spider):
    def gen_request(house_id=HOUSE_ID, **extra_meta):
        args = spider.gen_detail_request_args(DetailRequestMeta(house_id))
        args['meta'] = {**args['meta'], **extra_meta}
        return scrapy.Request(callback=spider.parse_detail, **args)

    return gen_request

@pytest.fixture
def list_request(spider):
    def gen_request():
        args = spider.gen_list_request_args(ListRequestMeta(6, '新北市', 0))
        return scrapy.Request(callback=spider.parse_list, **args)

    return gen_request

@pytest.fixture
def detail_response(detail_request):
    def gen_response(
        fixture='detail_591.html',
        status=200,
        house_id=HOUSE_ID,
        body=None,
        response_cls=HtmlResponse,
        **extra_meta
    ):
        request = detail_request(house_id, **extra_meta)
        if body is None:
            body = load_fixture(fixture)

        return response_cls(
            url=request.url,
            request=request,
            status=status,
            body=body.encode('utf-8')
        )

    return gen_response
