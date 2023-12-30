from abc import ABC, abstractmethod
import scrapy
from .enums import UNKNOWN_ENUM

# Prefer list request than detail request by default
DEFAULT_LIST_PRIORITY = 100

class RentalSpider(ABC, scrapy.Spider):
    """
    Abstract class for generic rental house spirder.
    This class define common interface of a rental spider, which allow developer to extend
    or decorate with their own logic.
    """
    def __init__(self, vendor: str, start_list=None, parse_list=None, parse_detail=None, **kwargs):
        super().__init__(**kwargs)
        self.vendor = vendor
        self.start_list = start_list if start_list else self.default_start_list
        self.parse_list = parse_list if parse_list else self.default_parse_list
        self.parse_detail = parse_detail if parse_detail else self.default_parse_detail

    def start_requests(self):
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
            'priority': DEFAULT_LIST_PRIORITY,
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
