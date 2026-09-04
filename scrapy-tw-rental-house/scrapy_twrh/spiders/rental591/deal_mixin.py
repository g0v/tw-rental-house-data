'''deals stage：走「已成交」列表產出成交事件（#229）。

每個縣市從第 1 頁翻起，直到整頁的成交日都早於 lookback 窗口或翻到空頁。
591 這個列表的分頁是「每頁 50 筆、頁距 30 筆」（相鄰兩頁固定重疊 20 筆，
順序確定、不隨時間洗牌），所以逐頁走不會漏、只會重複——事件冪等，
重複無害。
產出物＝GenericHouseItem（deal_status=DEAL、deal_time＝絕對成交日、
n_day_deal＝591 的「N天成交」）——寫回哪裡、要不要對未知物件建檔，
是 pipeline 的事，這裡只做 vendor 的純函數。
'''
import logging
from datetime import date, datetime, timedelta, timezone

from scrapy_twrh.items import GenericHouseItem
from scrapy_twrh.spiders import enums
from .deal_list_parser import parse_deal_list
from .request_generator import RequestGenerator
from .util import DealRequestMeta

# 成交日是台灣的日曆日；用固定 +8 讓 deal_time 帶時區、不依賴 Django
TAIPEI = timezone(timedelta(hours=8))


class DealMixin(RequestGenerator):
    # 翻頁上限（每頁 50 筆）：只是 runaway guard，lookback 窗口才是正常收單條件
    DEAL_PAGE_HARD_CAP = 2000

    def __init__(self, deal_lookback_days=2, deal_base_date=None, **kwargs):
        super().__init__(**kwargs)
        # 只收「成交日距 base_date ≤ N 天」的事件；日跑 2（今日＋昨日＋
        # 一天重疊，事件冪等），回補時開大
        self.deal_lookback_days = int(deal_lookback_days)
        # 相對成交日的基準日；pipeline 端以 pin 的日期覆寫（stage 不看時鐘）
        self.deal_base_date = deal_base_date
        self.deal_unknown_ages = 0

    def resolve_deal_base_date(self):
        base = self.deal_base_date
        if base is None:
            return date.today()
        if isinstance(base, datetime):
            return base.date()
        if isinstance(base, date):
            return base
        return datetime.strptime(str(base), '%Y-%m-%d').date()

    def default_start_deal(self):
        for city in self.target_cities:
            yield self.gen_deal_request(DealRequestMeta(
                city['id'],
                city['city'],
                1
            ))

    def default_parse_deal(self, response):
        meta = response.meta['rental']
        items = parse_deal_list(response.text)
        if not items:
            logging.info('[deal] %s page %d is empty, deals complete',
                         meta.name, meta.page)
            return

        base_date = self.resolve_deal_base_date()
        n_in_window = 0
        oldest_age = 0
        for item in items:
            age = item['deal_age_days']
            if age is None:
                self.deal_unknown_ages += 1
                logging.warning('[deal] %s: unknown deal_time %r on house %s',
                                meta.name, item.get('deal_time'), item['house_id'])
                continue
            oldest_age = max(oldest_age, age)
            if age > self.deal_lookback_days:
                continue
            n_in_window += 1
            deal_date = base_date - timedelta(days=age)
            yield GenericHouseItem(
                vendor=self.vendor,
                vendor_house_id=item['house_id'],
                vendor_house_url=item.get('url'),
                deal_status=enums.DealStatusType.DEAL,
                deal_time=datetime(deal_date.year, deal_date.month, deal_date.day,
                                   tzinfo=TAIPEI),
                n_day_deal=item['n_day_deal'],
            )

        logging.info('[deal] %s page %d: %d items, %d in %d-day window, oldest %d days',
                     meta.name, meta.page, len(items), n_in_window,
                     self.deal_lookback_days, oldest_age)

        # 倒序分頁：本頁最舊的都還在窗內，下一頁才可能還有窗內事件
        if oldest_age <= self.deal_lookback_days:
            if meta.page >= self.DEAL_PAGE_HARD_CAP:
                logging.error('[deal] %s hit page hard cap %d, stop probing',
                              meta.name, self.DEAL_PAGE_HARD_CAP)
                return
            yield self.gen_deal_request(DealRequestMeta(
                meta.id, meta.name, meta.page + 1))
