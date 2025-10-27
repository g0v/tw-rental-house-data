import json
from pathlib import Path
from datetime import datetime
from scrapy import signals
from scrapy.exporters import CsvItemExporter
from scrapy_twrh.items import GenericHouseItem, RawHouseItem
import logging

class CsvPipeline:
    def __init__(self):
        self.files = {}
        self.exporters = {}
        
    @classmethod
    def from_crawler(cls, crawler):
        pipeline = cls()
        crawler.signals.connect(pipeline.spider_opened, signals.spider_opened)
        crawler.signals.connect(pipeline.spider_closed, signals.spider_closed)
        return pipeline

    def spider_opened(self, spider):
        output_dir = Path('output')
        output_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = output_dir / f'houses_{timestamp}.csv'
        
        f = open(file_path, 'wb')
        self.files[spider] = f
        self.exporters[spider] = CsvItemExporter(f)
        self.exporters[spider].start_exporting()

    def spider_closed(self, spider):
        exporter = self.exporters.pop(spider)
        exporter.finish_exporting()
        f = self.files.pop(spider)
        f.close()

    def process_item(self, item, spider):
        if isinstance(item, GenericHouseItem):
            self.exporters[spider].export_item(item)
        return item
    
class CrawlerPipeline():
    def process_item(self, item, spider):
        # Export items based on type
        if isinstance(item, RawHouseItem):
            vendor = item['vendor']
            house_id = item['house_id']

            if item['is_list']:
                pass
            elif 'dict' in item:
                meta = item['dict']
                log = f'[RAW-DETAIL-DICT-{vendor}] house {house_id} | ${meta["price"]} | {meta["floor_ping"]}坪'
                if 'floor' in meta:
                    log += f' | {meta["floor"]}'
                if 'rough_coordinate' in meta:
                    log += f' | {meta["rough_coordinate"]}'
                logging.info(log)
        return item
