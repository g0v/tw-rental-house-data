'''欄位填充率監控（docs/dx-roadmap.md 2-2）。

熔斷抓的是「有報錯」的失敗；這裡抓的是另一種更危險的模式：
selector 失效但守衛式寫法讓欄位靜靜消失，item 照樣產出、統計一片綠。

作法：統計本次 run 每個 GenericHouseItem 欄位的填充率，寫進
<TWRH_FILL_RATE_DIR>/<date>.<spider>.json，並與同一 spider 的上一份報告比對 ——
掉幅超過 TWRH_FILL_RATE_DROP 就發 ERROR log（營運端由 Sentry 之類的 log 管道收）。

設定::

    EXTENSIONS = {
        'scrapy_twrh.extensions.fill_rate.FillRateMonitor': 30,
    }
    TWRH_FILL_RATE_DIR = 'path/to/fill-rates'   # 預設 ./fill-rates

報告日期優先讀 TWRH_TARGET_DATE 環境變數（YYYY-MM-DD，營運端 go.sh 會設，
讓跨午夜的 crawl 不會分裂成兩天），沒設才用當天日期。
'''
import datetime
import json
import logging
import os
from glob import glob

from scrapy import signals as scrapy_signals
from scrapy.exceptions import NotConfigured
from scrapy_twrh.items import GenericHouseItem

logger = logging.getLogger(__name__)


def is_filled(value):
    return value not in (None, '', [], {}, ())


def report_date():
    return os.environ.get('TWRH_TARGET_DATE') or datetime.date.today().isoformat()


class FillRateMonitor:
    def __init__(self, crawler):
        settings = crawler.settings
        if not settings.getbool('TWRH_FILL_RATE_ENABLED', True):
            raise NotConfigured('TWRH_FILL_RATE_ENABLED is off')

        self.report_dir = settings.get('TWRH_FILL_RATE_DIR', 'fill-rates')
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

        date = report_date()

        os.makedirs(self.report_dir, exist_ok=True)
        path = os.path.join(
            self.report_dir, '{}.{}.json'.format(date, spider.name))

        # 同一天可能分多個 batch 執行（go.sh 的 detail 迴圈）——
        # 累加既有報告，否則每個 batch 都把前一批的統計蓋掉
        n_items, counts = self.n_items, dict(self.counts)
        existing = self.load_report(path)
        if existing and existing.get('date') == date:
            n_items += existing.get('n_items', 0)
            for field, count in existing.get('counts', {}).items():
                counts[field] = counts.get(field, 0) + count

        report = {
            'date': date,
            'spider': spider.name,
            'n_items': n_items,
            'counts': counts,
            'rates': {field: count / n_items for field, count in counts.items()},
        }

        previous = self.load_previous(spider.name, exclude=path)
        with open(path, 'w') as report_file:
            json.dump(report, report_file, ensure_ascii=False, indent=2)

        logger.info(
            '[fill-rate] %s: %d items this run (%d today), report written to %s',
            spider.name, self.n_items, n_items, path)

        if previous:
            self.compare(spider.name, previous, report)

    def load_previous(self, spider_name, exclude):
        paths = sorted(
            p for p in glob(os.path.join(self.report_dir, '*.{}.json'.format(spider_name)))
            if os.path.abspath(p) != os.path.abspath(exclude))
        if not paths:
            return None
        return self.load_report(paths[-1])

    @staticmethod
    def load_report(path):
        try:
            with open(path) as report_file:
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
