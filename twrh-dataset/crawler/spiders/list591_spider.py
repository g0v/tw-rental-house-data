from scrapy import Request
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from .persist_queue import PersistQueue

class List591Spider(Rental591Spider):
    name = 'list591'

    def __init__(self, **kwargs):
        super().__init__(
            start_list=self.start_list_from_persist_queue,
            **kwargs
        )

        self.persist_queue = PersistQueue(
            vendor='591 租屋網',
            is_list=True,
            logger=self.logger,
            seed_parser=self.parse_seed,
            generate_request_args=self.gen_list_request_args,
            parse_response=self.parse_list_and_stop
        )

    def parse_seed (self, seed):
        return util.ListRequestMeta(*seed)

    def start_list_from_persist_queue (self):
        if not self.persist_queue.has_request() and not self.persist_queue.has_record():
            for city in self.target_cities:
                # let's do BFS
                self.persist_queue.gen_persist_request([
                    city['id'],
                    city['city'],
                    0
                ])

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
