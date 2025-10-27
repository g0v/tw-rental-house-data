import uuid
import scrapy
import traceback
from twisted.internet import threads
from django.db import connection
from rental.models import HouseTS, Vendor
from rental import models
from crawlerrequest.models import RequestTS
from crawlerrequest.enums import RequestType
from .progress_tracker import ProgressTracker

class PersistQueue(object):
    queue_length = 30
    n_live_spider = 0

    def __init__(
        self,
        vendor,
        is_list,
        logger,
        seed_parser,
        generate_request_args,
        parse_response,
        log_interval=60,
        **kwargs
    ):
        super().__init__(**kwargs)
        y = models.current_year()
        m = models.current_month()
        d = models.current_day()
        h = models.current_stepped_hour()

        self.spider_id = str(uuid.uuid4())
        self.logger = logger
        self.seed_parser = seed_parser
        self.generate_request_args = generate_request_args
        self.parse_response = parse_response
        
        # Initialize progress tracker
        self.progress_tracker = ProgressTracker(logger, log_interval=log_interval)
        
        try:
            self.vendor = Vendor.objects.get(
                name = vendor
            )
        except Vendor.DoesNotExist:
            raise Exception('Vendor "{}" is not defined.'.format(vendor))

        if is_list:
            self.request_type = RequestType.LIST
        else:
            self.request_type = RequestType.DETAIL

        self.ts = {
            'y': y,
            'm': m,
            'd': d,
            'h': h
        }

    def has_request(self):
        undone_requests = RequestTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
            # Ignore pending request since we will generate new one and rerun it anyway
            is_pending = False,
            vendor = self.vendor,
            request_type = self.request_type
        )[:1]

        return undone_requests.count() > 0
    
    def get_total_count(self):
        """Get the total number of requests in the queue."""
        total = RequestTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
            vendor = self.vendor,
            request_type = self.request_type
        ).count()
        return total
    
    def init_progress_tracking(self):
        """Initialize progress tracking with the current total count."""
        total = self.get_total_count()
        self.progress_tracker.set_total(total)
        return total

    def has_record(self):
        today_houses = HouseTS.objects.filter(
            year = self.ts['y'],
            month = self.ts['m'],
            day = self.ts['d'],
            hour = self.ts['h'],
            vendor = self.vendor
        )[:1]

        return today_houses.count() > 0

    def gen_persist_request(self, seed):
        RequestTS.objects.create(
            request_type=self.request_type,
            vendor=self.vendor,
            seed=seed
        )

    def next_request(self):
        if self.n_live_spider >= self.queue_length:
            # At most self.queue_length in memory
            return None

        # #21, temp workaround to get next_request ASAP
        # this operation is still not atomic, different session may get the same request
        with connection.cursor() as cursor:
            sql = (
                'update request_ts set owner = %s where id = ('
                'select id from request_ts where year = %s and month = %s '
                'and day = %s and hour = %s and vendor_id = %s and request_type = %s '
                'and is_pending = %s and owner is null order by id limit 1)'
            )
            a = cursor.execute(sql, [
                self.spider_id,
                self.ts['y'],
                self.ts['m'],
                self.ts['d'],
                self.ts['h'],
                self.vendor.id,
                self.request_type.value,
                False
            ])

        next_row = RequestTS.objects.filter(
            year=self.ts['y'],
            month=self.ts['m'],
            day=self.ts['d'],
            hour=self.ts['h'],
            vendor=self.vendor,
            request_type=self.request_type,
            is_pending=False,
            owner=self.spider_id
        ).order_by('created')

        next_row = next_row.first()

        if next_row is None:
            return None

        next_row.is_pending = True
        next_row.save()
        self.n_live_spider += 1

        rental_meta = self.seed_parser(next_row.seed)

        request_args = {
            **self.generate_request_args(rental_meta),
            # overwrite callback directly, 
            # as we know where to find real parser
            'callback': self.parser_wrapper
        }

        if 'meta' not in request_args:
            request_args['meta'] = {
                'rental': rental_meta,
                'db_request': next_row
            }
        elif 'db_request' not in request_args['meta']:
            request_args['meta']['db_request'] = next_row

        return scrapy.Request(**request_args)

    def parser_wrapper(self, response):
        db_request = response.meta['db_request']
        db_request.last_status = response.status
        db_request.save()

        meta = response.meta.get('rental', {})

        try:
            for item in self.parse_response(response):
                if item is True:
                    db_request.delete()
                    # Track progress after successful completion
                    self.progress_tracker.increment()
                else:
                    yield item
        except Exception:
            self.logger.error(
                'Parser error in {} when handle meta {}. [{}] - {:.128}'.format(
                    self.vendor.name,
                    meta,
                    response.status,
                    response.text
                )
            )
            traceback.print_exc()

        self.n_live_spider -= 1
        # quick fix for concurrency issue
        mercy = 10
        while True:
            next_request = self.next_request()
            if next_request:
                yield next_request
            elif mercy < 0:
                break
            else:
                mercy -= 1
