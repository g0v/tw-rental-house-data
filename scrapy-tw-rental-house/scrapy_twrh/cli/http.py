'''純 HTTP fetcher，供 CLI 手動測試用。

不走 scrapy，因此不需要 scrapy 專案設定。
591 以 30x 表示房源狀態，所以不跟隨 redirect、原樣回報 status code。
'''
import time
import urllib.request
import urllib.error

from scrapy_twrh.spiders.rental591.rental591_spider import DEFAULT_USER_AGENT

# 與 spider 同一組 UA：591 對 scrapy 預設 UA 回 403
DEFAULT_UA = DEFAULT_USER_AGENT


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Fetcher:
    def __init__(self, user_agent=None, delay=1.0):
        self.user_agent = user_agent or DEFAULT_UA
        self.delay = delay
        self._opener = urllib.request.build_opener(_NoRedirect())
        self._last_request_at = 0.0

    def get(self, url):
        '''回傳 (status, body_bytes)；30x/4xx 不丟例外，網路層錯誤才丟。'''
        wait = self.delay - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

        req = urllib.request.Request(url, headers={
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml',
        })
        try:
            with self._opener.open(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()
