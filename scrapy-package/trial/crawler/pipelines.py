import logging
from scrapy_twrh.items import GenericHouseItem, RawHouseItem

class CrawlerPipeline():

    def process_item(self, item, spider):
        if type(item) is RawHouseItem:
            if item['is_list']:
                logging.info('[RAW-LIST-{}] house {}'.format(item['vendor'], item['house_id']))
            else:
                logging.info('[RAW-DETAIL-{}] house {}'.format(item['vendor'], item['house_id']))
        elif type(item) is GenericHouseItem:
            logging.info('[GENERIC-{}] house {} in {}'.format(item['vendor'], item['vendor_house_id'], item['top_region']))
