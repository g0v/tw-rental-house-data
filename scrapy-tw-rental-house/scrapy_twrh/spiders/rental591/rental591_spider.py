import scrapy # type: ignore
from .list_mixin import ListMixin
from .detail_mixin import DetailMixin
from .all_591_cities import all_591_cities
# from .util import SESSION_ENDPOINT

# both list and detail pages are downloaded by plain HTTP, and 591 serves those
# to a browser UA only
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
)

class Rental591Spider(ListMixin, DetailMixin):
    name = 'rental591'
    # not used since #176
    # csrf_token = ''
    # session = {
    #     '591_new_session': None,
    #     'PHPSESSID': None
    # }

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

    @classmethod
    def update_settings(cls, settings):
        super().update_settings(settings)

        # 591 answers Scrapy's default User-Agent with 403, so a project which
        # never set one would get nothing at all. Only fill in the gap, a
        # project that picked its own UA keeps it.
        if (settings.getpriority('USER_AGENT') or 0) <= 0:
            settings.set('USER_AGENT', DEFAULT_USER_AGENT, priority='spider')

        # for backward compatibility
        settings.set('TWISTED_REACTOR', 'twisted.internet.asyncioreactor.AsyncioSelectorReactor', priority='spider')

