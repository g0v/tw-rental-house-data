'''Offline harness for the parser tests.

Every page is read from tests/fixtures, so the suite keeps passing after the
houses are gone from 591, and needs neither a DB nor a browser. Sockets are
blocked while it runs, so a test which crawls by accident fails loudly instead
of reaching 591.
'''
import os
import socket

import pytest
from scrapy.http import HtmlResponse

from scrapy_twrh.spiders.rental591 import Rental591Spider
from scrapy_twrh.spiders.rental591.util import DetailRequestMeta

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

# the fixtures carry no house id, everything identifying is replaced by a
# synthetic value. This is only a label, no test ever requests it.
HOUSE_ID = '10000001'


def load_fixture(name):
    with open(os.path.join(FIXTURE_DIR, name), encoding='utf-8') as fixture:
        return fixture.read()


@pytest.fixture(autouse=True)
def in_tmp_cwd(tmp_path, monkeypatch):
    '''keep whatever a spider writes on startup out of the repository'''
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise RuntimeError('tests must not crawl, please add a fixture instead')

    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)


@pytest.fixture
def spider():
    return Rental591Spider()


@pytest.fixture
def detail_response(spider):
    '''the response parse_detail would get for a fixture'''
    def gen_response(fixture=None, status=200, house_id=HOUSE_ID, body=None):
        request = spider.gen_detail_request(DetailRequestMeta(house_id))

        if body is None:
            body = load_fixture(fixture)

        return HtmlResponse(
            url=request.url,
            request=request,
            status=status,
            body=body.encode('utf-8')
        )

    return gen_response
