'''The Phase 2 safety nets: error-rate breaker and fill-rate monitor.

Offline, on a stub crawler — the breaker must trip on the custom
scrapy_twrh.signals (native spider_error never fires when a parser_wrapper
swallows exceptions), and the fill-rate monitor must flag a field whose fill
rate collapses between two runs, which is the silent failure statscheck can
never see.
'''
import json
import logging

import pytest
from scrapy.settings import Settings
from scrapy.signalmanager import SignalManager

from scrapy_twrh import signals as twrh_signals
from scrapy_twrh.extensions.breaker import ErrorRateBreaker
from scrapy_twrh.extensions.fill_rate import FillRateMonitor
from scrapy_twrh.items import GenericHouseItem


class StubEngine:
    def __init__(self):
        self.closed = None

    def close_spider(self, spider, reason):
        self.closed = reason


class StubCrawler:
    def __init__(self, **settings):
        self.settings = Settings(settings)
        self.signals = SignalManager(self)
        self.engine = StubEngine()


class StubSpider:
    name = 'stub591'


def test_breaker_trips_on_custom_signals():
    crawler = StubCrawler(
        TWRH_BREAKER_MIN_SAMPLES=10, TWRH_BREAKER_THRESHOLD=0.5)
    breaker = ErrorRateBreaker.from_crawler(crawler)  # keep a ref: signals connect weakly
    spider = StubSpider()

    for _ in range(5):
        crawler.signals.send_catch_log(twrh_signals.parse_success)
    for _ in range(5):
        crawler.signals.send_catch_log(twrh_signals.parse_error, spider=spider)

    assert crawler.engine.closed == 'error_rate_exceeded'


def test_breaker_stays_quiet_below_threshold():
    crawler = StubCrawler(
        TWRH_BREAKER_MIN_SAMPLES=10, TWRH_BREAKER_THRESHOLD=0.5)
    breaker = ErrorRateBreaker.from_crawler(crawler)  # keep a ref: signals connect weakly
    spider = StubSpider()

    for _ in range(20):
        crawler.signals.send_catch_log(twrh_signals.parse_success)
    for _ in range(4):
        crawler.signals.send_catch_log(twrh_signals.parse_error, spider=spider)

    assert crawler.engine.closed is None


def test_breaker_needs_min_samples():
    crawler = StubCrawler(
        TWRH_BREAKER_MIN_SAMPLES=10, TWRH_BREAKER_THRESHOLD=0.5)
    breaker = ErrorRateBreaker.from_crawler(crawler)  # keep a ref: signals connect weakly
    spider = StubSpider()

    # 100% failure, but not enough samples yet
    for _ in range(9):
        crawler.signals.send_catch_log(twrh_signals.parse_error, spider=spider)

    assert crawler.engine.closed is None


def run_fill_rate_once(tmp_path, items):
    from scrapy import signals as scrapy_signals

    crawler = StubCrawler(
        TWRH_FILL_RATE_DIR=str(tmp_path),
        TWRH_FILL_RATE_MIN_SAMPLES=2,
        TWRH_FILL_RATE_DROP=0.3,
    )
    monitor = FillRateMonitor.from_crawler(crawler)  # keep a ref: signals connect weakly
    spider = StubSpider()
    for item in items:
        crawler.signals.send_catch_log(
            scrapy_signals.item_scraped, item=item, response=None, spider=spider)
    crawler.signals.send_catch_log(scrapy_signals.spider_closed, spider=spider)


def test_fill_rate_writes_report(tmp_path, monkeypatch):
    monkeypatch.setenv('TWRH_TARGET_DATE', '2026-08-25')
    run_fill_rate_once(tmp_path, [
        GenericHouseItem(vendor='591 租屋網', vendor_house_id='1', monthly_price=1000),
        GenericHouseItem(vendor='591 租屋網', vendor_house_id='2'),
    ])

    report = json.loads((tmp_path / '2026-08-25.stub591.json').read_text())
    assert report['n_items'] == 2
    assert report['rates']['monthly_price'] == 0.5
    assert report['rates']['vendor_house_id'] == 1.0


def test_fill_rate_accumulates_same_day_batches(tmp_path, monkeypatch):
    # go.sh 的 detail 迴圈同一天會跑多個 batch，報告必須累加而非覆蓋
    monkeypatch.setenv('TWRH_TARGET_DATE', '2026-08-25')
    run_fill_rate_once(tmp_path, [
        GenericHouseItem(vendor='591 租屋網', vendor_house_id='1', monthly_price=1000),
    ])
    run_fill_rate_once(tmp_path, [
        GenericHouseItem(vendor='591 租屋網', vendor_house_id='2'),
        GenericHouseItem(vendor='591 租屋網', vendor_house_id='3'),
    ])

    report = json.loads((tmp_path / '2026-08-25.stub591.json').read_text())
    assert report['n_items'] == 3
    assert report['counts']['monthly_price'] == 1
    assert report['rates']['monthly_price'] == pytest.approx(1 / 3)


def test_fill_rate_flags_a_collapsed_field(tmp_path, monkeypatch, caplog):
    full = [GenericHouseItem(vendor='591 租屋網', vendor_house_id=str(i),
                             monthly_price=1000) for i in range(3)]
    empty = [GenericHouseItem(vendor='591 租屋網', vendor_house_id=str(i))
             for i in range(3)]

    monkeypatch.setenv('TWRH_TARGET_DATE', '2026-08-24')
    run_fill_rate_once(tmp_path, full)

    monkeypatch.setenv('TWRH_TARGET_DATE', '2026-08-25')
    with caplog.at_level(logging.ERROR):
        run_fill_rate_once(tmp_path, empty)

    assert any('monthly_price' in record.message and 'dropped' in record.message
               for record in caplog.records)
