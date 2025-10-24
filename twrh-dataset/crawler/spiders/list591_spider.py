from scrapy import Request, signals
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from .persist_queue import PersistQueue

class List591Spider(Rental591Spider):
    name = 'list591'

    def __init__(self, append=False, **kwargs):
        super().__init__(
            start_list=self.start_list_from_persist_queue,
            **kwargs
        )

        self.append = append == 'True' or append == True

        self.persist_queue = PersistQueue(
            vendor='591 租屋網',
            is_list=True,
            logger=self.logger,
            seed_parser=self.parse_seed,
            generate_request_args=self.gen_list_request_args,
            parse_response=self.parse_list_and_stop
        )
    
    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super(List591Spider, cls).from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        return spider
    
    def spider_closed(self, spider=None):
        self.persist_queue.progress_tracker.log_final()

    def parse_seed (self, seed):
        return util.ListRequestMeta(*seed)

    def start_list_from_persist_queue (self):
        # In append mode, skip if has_record() and generate persist request if not has_request
        # In normal mode, only generate if no request and no record
        should_generate = False
        
        if self.append:
            should_generate = True
        elif not self.persist_queue.has_record():
            should_generate = True
        
        if should_generate:
            self.logger.info('Generating initial requests (append mode: {})'.format(self.append))
            for city in self.target_cities:
                # let's do BFS
                self.persist_queue.gen_persist_request([
                    city['id'],
                    city['city'],
                    0
                ])
        
        # Initialize progress tracking
        self.persist_queue.init_progress_tracking()

        while True:
            next_request = self.persist_queue.next_request()
            if next_request:
                yield next_request
            else:
                break

    def parse_list_and_stop(self, response):
        for item in self.default_parse_list(response):
            if isinstance(item, Request):
                meta = item.meta['rental']
                if isinstance(meta, util.ListRequestMeta):
                    self.persist_queue.gen_persist_request(meta)
                continue
            else:
                yield item
        yield True
