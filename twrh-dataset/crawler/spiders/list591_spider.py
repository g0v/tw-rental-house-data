from scrapy import Request, signals
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from rental.enums import TopRegionType
from .persist_queue import PersistQueue

class List591Spider(Rental591Spider):
    name = 'list591'

    def __init__(self, append=False, start_early=False, **kwargs):
        # scrapy -a target_cities=A,B 傳進來是字串，直接迭代會變成逐字比對
        if isinstance(kwargs.get('target_cities'), str):
            kwargs['target_cities'] = kwargs['target_cities'].split(',')

        super().__init__(
            start_list=self.start_list_from_persist_queue,
            **kwargs
        )

        self.append = append == 'True' or append == True
        self.start_early = start_early == 'True' or start_early == True

        self.persist_queue = PersistQueue(
            vendor='591 租屋網',
            is_list=True,
            logger=self.logger,
            seed_parser=self.parse_seed,
            generate_request_args=self.gen_list_request_args,
            parse_response=self.parse_list_and_stop,
            start_early=self.start_early,
            spider=self
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
        # In append mode, always regenerate seeds.
        # In normal mode, generate per city — has_record() must be scoped to the
        # city, or a same-day run for city B is silently skipped after city A.
        for city in self.target_cities:
            if not self.append and self.persist_queue.has_record(
                    top_region=TopRegionType[city['city']]):
                continue
            self.logger.info('Generating initial requests for {} (append mode: {})'.format(
                city['city'], self.append))
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
