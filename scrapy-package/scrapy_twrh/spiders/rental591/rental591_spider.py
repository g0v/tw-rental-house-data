import scrapy
from .list_mixin import ListMixin
from .detail_mixin import DetailMixin
from .all_591_cities import all_591_cities
from .util import SESSION_ENDPOINT

class Rental591Spider(ListMixin, DetailMixin):
    name = 'rental591'

    def __init__(self, target_cities=None, **kwargs):
        super().__init__(
            vendor='591 租屋網',
            **kwargs
        )

        if target_cities:
            lookup_dict = {}
            for city in all_591_cities:
                lookup_dict[city['city']] = city
            for city in target_cities:
                if city in lookup_dict:
                    self.target_cities.append(lookup_dict[city])
        else:
            self.target_cities = all_591_cities

    def start_requests(self):
        # 591 require a valid session to start request, #27
        yield scrapy.Request(
            url=SESSION_ENDPOINT,
            dont_filter=True,
            callback=self.handle_session_init,
        )

    def handle_session_init(self, response):
        self.csrf_token = response.css('meta[name="csrf-token"]').xpath('@content').extract_first()

        for cookie in response.headers.getlist('Set-Cookie'):
            cookie_tokens = cookie.decode('utf-8').split('; ')
            if cookie_tokens and cookie_tokens[0].startswith('591_new_session='):
                self.session_token = cookie_tokens[0].split('=')[1]
                break

        for item in self.start_list():
            yield item
