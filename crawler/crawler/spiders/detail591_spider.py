import traceback
from django.db import transaction
from rental.models import House
from rental import enums
from scrapy_twrh.spiders.rental591 import Rental591Spider, util
from .persist_queue import PersistQueue

class Detail591Spider(Rental591Spider):
    name = "detail591"

    def __init__(self, **kwargs):
        super().__init__(
            start_list=self.start_detail_requests,
            **kwargs
        )

        self.persist_queue = PersistQueue(
            vendor='591 租屋網',
            is_list=False,
            logger=self.logger,
            seed_parser=self.parse_seed,
            generate_request_args=self.gen_detail_request_args,
            parse_response=self.parse_detail
        )

    def parse_seed(self, seed):
        return util.DetailRequestMeta(*seed)

    def start_detail_requests(self):

        if not self.persist_queue.has_request():
            # find all opened houses and crawl all of them
            houses = House.objects.filter(
                deal_status = enums.DealStatusType.OPENED
            ).values('vendor_house_id')

            self.logger.info('generating request: {}'.format(houses.count()))

            with transaction.atomic():
                try:
                    for house in houses:
                        self.persist_queue.gen_persist_request([house['vendor_house_id']])
                except:
                    traceback.print_exc()

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
