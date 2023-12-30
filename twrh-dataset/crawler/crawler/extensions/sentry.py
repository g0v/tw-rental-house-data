import logging
from raven.handlers.logging import SentryHandler
from raven.conf import setup_logging
from scrapy.exceptions import NotConfigured

class SentryLogger(object):
    def __init__(self, dsn):
        if dsn:
            # ref: https://blog.windrunner.me/tool/sentry.html#%E5%92%8C-scrapy-%E9%9B%86%E6%88%90
            handler = SentryHandler(dsn)
            handler.setLevel(logging.ERROR)
            setup_logging(handler)

    @classmethod
    def from_crawler(cls, crawler):
        dsn = crawler.settings.get("SENTRY_DSN", None)
        if dsn is None:
            raise NotConfigured('No SENTRY_DSN configured')
        return cls(dsn=dsn)
