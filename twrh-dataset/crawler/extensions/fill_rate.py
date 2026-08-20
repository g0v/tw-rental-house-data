'''欄位填充率監控（docs/dx-roadmap.md 2-2）。

熔斷抓的是「有報錯」的失敗；這裡抓的是另一種更危險的模式：
selector 失效但守衛式寫法讓欄位靜靜消失，item 照常入庫、statscheck 一片綠。

作法：統計本次 run 每個 GenericHouseItem 欄位的填充率，寫進
logs/fill-rates/<date>.<spider>.json，並與同一 spider 的上一份報告比對 ——
掉幅超過 TWRH_FILL_RATE_DROP 就發 ERROR log（SentryLogger 會收）。
'''
import json
import logging
import os
from glob import glob

from scrapy import signals as scrapy_signals
from scrapy.exceptions import NotConfigured
from scrapy_twrh.items import GenericHouseItem

logger = logging.getLogger(__name__)

REPORT_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'logs', 'fill-rates')


def is_filled(value):
    return value not in (None, '', [], {}, ())


class FillRateMonitor:
    def __init__(self, crawler):
        settings = crawler.settings
        if not settings.getbool('TWRH_FILL_RATE_ENABLED', True):
            raise NotConfigured('TWRH_FILL_RATE_ENABLED is off')

        self.drop_threshold = settings.getfloat('TWRH_FILL_RATE_DROP', 0.3)
        self.min_samples = settings.getint('TWRH_FILL_RATE_MIN_SAMPLES', 20)
        self.n_items = 0
        self.counts = {}

        crawler.signals.connect(self.on_item, signal=scrapy_signals.item_scraped)
        crawler.signals.connect(self.on_close, signal=scrapy_signals.spider_closed)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def on_item(self, item, response, spider, **_kwargs):
        if not isinstance(item, GenericHouseItem):
            return
        self.n_items += 1
        for field in item.fields:
            if field in item and is_filled(item[field]):
                self.counts[field] = self.counts.get(field, 0) + 1

    def rates(self):
        return {
            field: self.counts.get(field, 0) / self.n_items
            for field in self.counts
        } if self.n_items else {}

    def on_close(self, spider, **_kwargs):
        if not self.n_items:
            return

        from crawler.utils import now_tuple
        y, m, d, _h = now_tuple()
        date = '{}-{:02d}-{:02d}'.format(y, m, d)

        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(
            REPORT_DIR, '{}.{}.json'.format(date, spider.name))

        report = {
            'date': date,
            'spider': spider.name,
            'n_items': self.n_items,
            'counts': self.counts,
            'rates': self.rates(),
        }

        previous = self.load_previous(spider.name, exclude=path)
        with open(path, 'w') as report_file:
            json.dump(report, report_file, ensure_ascii=False, indent=2)

        logger.info(
            '[fill-rate] %s: %d items, report written to %s',
            spider.name, self.n_items, path)

        if previous:
            self.compare(spider.name, previous, report)

    def load_previous(self, spider_name, exclude):
        paths = sorted(
            p for p in glob(os.path.join(REPORT_DIR, '*.{}.json'.format(spider_name)))
            if os.path.abspath(p) != os.path.abspath(exclude))
        if not paths:
            return None
        try:
            with open(paths[-1]) as report_file:
                return json.load(report_file)
        except (OSError, ValueError):
            return None

    def compare(self, spider_name, previous, current):
        if previous.get('n_items', 0) < self.min_samples or \
                current['n_items'] < self.min_samples:
            return

        for field, prev_rate in previous.get('rates', {}).items():
            cur_rate = current['rates'].get(field, 0.0)
            if prev_rate - cur_rate >= self.drop_threshold:
                logger.error(
                    '[fill-rate] %s.%s dropped %.0f%% -> %.0f%% '
                    '(prev %s, now %s items) — selector drift?',
                    spider_name, field,
                    prev_rate * 100, cur_rate * 100,
                    previous.get('date'), current['date'])
