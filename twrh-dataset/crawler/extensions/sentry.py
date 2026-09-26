import logging
import sentry_sdk
from scrapy.exceptions import NotConfigured

class SentryLogger(object):
    def __init__(self, dsn):
        if dsn:
            sentry_sdk.init(
                dsn=dsn,
                traces_sample_rate=0.1,
                profiles_sample_rate=0.1,
                # S6：爬蟲行程不再起 Django；自動整合會試 import django（拿到 twrh-dataset/django/
                # 這個空目錄），關掉。錯誤回報靠預設整合（logging／excepthook）
                auto_enabling_integrations=False,
            )
            sentry_sdk.set_level(logging.ERROR)

    @classmethod
    def from_crawler(cls, crawler):
        dsn = crawler.settings.get("SENTRY_DSN", None)
        if dsn is None:
            raise NotConfigured('No SENTRY_DSN configured')
        return cls(dsn=dsn)
