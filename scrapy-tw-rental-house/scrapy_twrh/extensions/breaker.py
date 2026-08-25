'''錯誤率熔斷（docs/dx-roadmap.md 2-1）。

滑動視窗統計 parse 成敗：樣本數 >= TWRH_BREAKER_MIN_SAMPLES 且
失敗率 >= TWRH_BREAKER_THRESHOLD 時關閉 spider，避免 591 改版後
繼續空轉幾千個 request。

只設 CLOSESPIDER_ERRORCOUNT 沒有用 —— 營運端的 parser_wrapper 吃掉例外後
scrapy 收不到 spider_error，所以這裡聽的是 scrapy_twrh.signals 的自訂訊號，
由包住 parser 的那一層主動送；native spider_error 也一併計入，讓沒有自己
包 parser 的 spider（例外自然逃出 callback）同樣受熔斷保護。

啟用方式（scrapy settings）::

    EXTENSIONS = {
        'scrapy_twrh.extensions.breaker.ErrorRateBreaker': 20,
    }
'''
import logging
from collections import deque

from scrapy import signals as scrapy_signals
from scrapy.exceptions import NotConfigured

from scrapy_twrh import signals as twrh_signals

logger = logging.getLogger(__name__)


class ErrorRateBreaker:
    def __init__(self, crawler):
        settings = crawler.settings
        if not settings.getbool('TWRH_BREAKER_ENABLED', True):
            raise NotConfigured('TWRH_BREAKER_ENABLED is off')

        self.crawler = crawler
        self.threshold = settings.getfloat('TWRH_BREAKER_THRESHOLD', 0.5)
        self.min_samples = settings.getint('TWRH_BREAKER_MIN_SAMPLES', 20)
        window = settings.getint('TWRH_BREAKER_WINDOW', 100)
        self.outcomes = deque(maxlen=window)
        self.tripped = False

        crawler.signals.connect(self.on_success, signal=twrh_signals.parse_success)
        crawler.signals.connect(self.on_error, signal=twrh_signals.parse_error)
        # 例外若真的逃出 callback（未走 parser_wrapper 的 spider），也算失敗
        crawler.signals.connect(self.on_spider_error, signal=scrapy_signals.spider_error)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def on_success(self, **_kwargs):
        self.outcomes.append(True)

    def on_error(self, spider=None, **_kwargs):
        self.outcomes.append(False)
        self.check(spider)

    def on_spider_error(self, failure, spider, **_kwargs):
        self.outcomes.append(False)
        self.check(spider)

    def check(self, spider):
        if self.tripped or len(self.outcomes) < self.min_samples:
            return

        n_error = self.outcomes.count(False)
        rate = n_error / len(self.outcomes)
        if rate < self.threshold:
            return

        self.tripped = True
        logger.critical(
            '[breaker] error rate %.0f%% (%d/%d) >= %.0f%%, closing spider %s',
            rate * 100, n_error, len(self.outcomes),
            self.threshold * 100, getattr(spider, 'name', '?'))
        self.crawler.engine.close_spider(spider, reason='error_rate_exceeded')
