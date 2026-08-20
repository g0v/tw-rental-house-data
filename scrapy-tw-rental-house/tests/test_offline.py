import socket

import pytest

from .conftest import DETAIL_URL, load_fixture

def test_tests_never_crawl():
    '''
    Guard of the guard, see the no_network fixture in conftest.
    Fixtures under tests/fixtures are the only source of 591 HTML here.
    '''
    with pytest.raises(RuntimeError):
        socket.create_connection(('rent.591.com.tw', 443))

    with pytest.raises(RuntimeError):
        socket.getaddrinfo('rent.591.com.tw', 443)

def test_detail_url_is_only_a_label(detail_response):
    response = detail_response()

    assert response.url == DETAIL_URL
    assert response.text == load_fixture('detail_591.html')
