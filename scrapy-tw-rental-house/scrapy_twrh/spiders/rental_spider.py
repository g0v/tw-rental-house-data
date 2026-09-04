from abc import ABC, abstractmethod
import scrapy
from .enums import UNKNOWN_ENUM

class RentalSpider(ABC, scrapy.Spider):
    # Prefer list request than detail request by default
    DEFAULT_LIST_PRIORITY = 100

    """
    Abstract class for generic rental house spirder.
    This class define common interface of a rental spider, which allow developer to extend
    or decorate with their own logic.
    """
    def __init__(self, vendor: str, start_list=None, parse_list=None, parse_detail=None,
                 start_deal=None, parse_deal=None, **kwargs):
        super().__init__(**kwargs)
        self.vendor = vendor
        self.start_list = start_list if start_list else self.default_start_list
        self.parse_list = parse_list if parse_list else self.default_parse_list
        self.parse_detail = parse_detail if parse_detail else self.default_parse_detail
        # deals stage（#229）：vendor 可選，預設 NotImplemented——既有的
        # 第三方子類不需實作
        self.start_deal = start_deal if start_deal else self.default_start_deal
        self.parse_deal = parse_deal if parse_deal else self.default_parse_deal

    async def start(self):
        # scrapy 2.13+ 以 async start() 供給起始請求，2.18 起不再 fallback 到
        # deprecated 的 start_requests()——沒有這個方法時 spider 會零請求靜默收單
        for item in self.start_requests():
            yield item

    def start_requests(self):
        # scrapy < 2.13 只認得這個入口，保留以維持相容
        for item in self.start_list():
            yield item

    def gen_list_request(self, rental_meta) -> scrapy.Request:
        """
        Generates scrapy.Request for list from meta data.
        rental_meta will be put into meta['rental'], so to make request serializable.
        """
        args = {
            'callback': self.parse_list,
            'meta': {
                'rental': rental_meta
            },
            'priority': self.DEFAULT_LIST_PRIORITY,
            **self.gen_list_request_args(rental_meta)
        }
        return scrapy.Request(**args)

    def gen_detail_request(self, rental_meta) -> scrapy.Request:
        """
        Generates scrapy.Request for detail from meta data.
        rental_meta will be put into meta['rental'], so to make request serializable.
        """
        args = {
            'callback': self.parse_detail,
            'meta': {
                'rental': rental_meta
            },
            **self.gen_detail_request_args(rental_meta)
        }
        return scrapy.Request(**args)

    def gen_deal_request(self, rental_meta) -> scrapy.Request:
        """
        Generates scrapy.Request for a deal list page from meta data.
        rental_meta will be put into meta['rental'], so to make request serializable.
        """
        args = {
            'callback': self.parse_deal,
            'meta': {
                'rental': rental_meta
            },
            'priority': self.DEFAULT_LIST_PRIORITY,
            **self.gen_deal_request_args(rental_meta)
        }
        return scrapy.Request(**args)

    def get_enum(self, enum_cls, house_id, value):
        try:
            enum = enum_cls[value]
        except KeyError:
            self.logger.error('Unknown property: {}/{} in house {}'.format(
                value,
                enum_cls.__name__,
                house_id
            ))
            enum = UNKNOWN_ENUM

        return enum


    @abstractmethod
    def gen_list_request_args(self, rental_meta):
        pass

    @abstractmethod
    def gen_detail_request_args(self, meta):
        pass

    @abstractmethod
    def default_start_list(self):
        pass

    @abstractmethod
    def default_parse_list(self, response):
        pass

    @abstractmethod
    def default_parse_detail(self, response):
        pass

    # --- deals stage（可選）：成交事件不一定來自 detail 頁，vendor 自行決定
    #     來源（591 自 2026 改版起只在「已成交」列表提供）。
    #     不設 abstract，避免既有子類因新增介面而失效。
    def gen_deal_request_args(self, rental_meta):
        raise NotImplementedError('{} does not provide deal events'.format(self.vendor))

    def default_start_deal(self):
        raise NotImplementedError('{} does not provide deal events'.format(self.vendor))

    def default_parse_deal(self, response):
        raise NotImplementedError('{} does not provide deal events'.format(self.vendor))
