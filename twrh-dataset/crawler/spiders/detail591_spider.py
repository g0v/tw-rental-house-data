import traceback
from django.db import transaction
from scrapy import signals
from rental.models import House
from rental import enums
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from .persist_queue import PersistQueue

class Detail591Spider(Rental591Spider):
    name = "detail591"

    def __init__(self, append=False, **kwargs):
        super().__init__(
            start_list=self.start_detail_requests,
            **kwargs
        )

        self.append = append == 'True' or append == True
        
        self.persist_queue = PersistQueue(
            vendor='591 租屋網',
            is_list=False,
            logger=self.logger,
            seed_parser=self.parse_seed,
            generate_request_args=self.gen_detail_request_args,
            parse_response=self.parse_detail_and_done
        )
    
    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super(Detail591Spider, cls).from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        return spider
    
    def spider_closed(self, spider=None):
        self.persist_queue.progress_tracker.log_final()

    def parse_seed(self, seed):
        return util.DetailRequestMeta(*seed)

    def parse_detail_and_done (self, response):
        for item in self.default_parse_detail(response):
            if item:
                yield item
        yield True

    def start_detail_requests(self):

        if not self.persist_queue.has_request():
            # find all opened houses and crawl all of them
            query = House.objects.filter(
                deal_status = enums.DealStatusType.OPENED
            )
            
            # In append mode, also filter by monthly_price is null
            if self.append:
                query = query.filter(monthly_price__isnull=True)
                
            houses = query.values('vendor_house_id')

            total = houses.count()
            self.logger.info('generating request: {} (append mode: {})'.format(total, self.append))

            with transaction.atomic():
                try:
                    for house in houses:
                        self.persist_queue.gen_persist_request([house['vendor_house_id']])
                except:
                    traceback.print_exc()
        
        # Initialize progress tracking
        self.persist_queue.init_progress_tracking()

        # quick fix for concurrency issue
        mercy = 10
        while True:
            next_request = self.persist_queue.next_request()
            if next_request:
                yield next_request
            elif mercy < 0:
                break
            else:
                mercy -= 1
