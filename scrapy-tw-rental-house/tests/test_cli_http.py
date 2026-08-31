'''Fetcher 韌性：網路層錯誤記 status 0 續跑，不炸整場 survey/harvest。'''
import http.client
import urllib.error

import pytest

from scrapy_twrh.cli.http import Fetcher


class _BoomOpener:
    def __init__(self, exc):
        self.exc = exc

    def open(self, req, timeout=None):
        raise self.exc


@pytest.mark.parametrize('exc', [
    urllib.error.URLError('dns fail'),
    ConnectionResetError(104, 'Connection reset by peer'),
    TimeoutError('timed out'),
    http.client.RemoteDisconnected('closed without response'),
])
def test_network_error_returns_status_0(exc):
    fetcher = Fetcher(delay=0)
    fetcher._opener = _BoomOpener(exc)
    assert fetcher.get('https://example.invalid/x') == (0, b'')
