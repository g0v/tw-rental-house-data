import scrapy # type: ignore
from .list_mixin import ListMixin
from .detail_mixin import DetailMixin
from .deal_mixin import DealMixin
from .all_591_cities import all_591_cities
# from .util import SESSION_ENDPOINT

class Rental591Spider(ListMixin, DetailMixin, DealMixin):
    name = 'rental591'
    # not used since #176
    # csrf_token = ''
    # session = {
    #     '591_new_session': None,
    #     'PHPSESSID': None
    # }

    def __init__(self, target_cities=None, deals_only=False, **kwargs):
        super().__init__(
            vendor='591 租屋網',
            **kwargs
        )
        # -a deals_only=True：只走「已成交」列表產成交事件（#229），
        # 不爬 list／detail
        if deals_only == 'True' or deals_only is True:
            self.start_list = self.start_deal

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
        # both list and detail pages are downloaded by plain HTTP — 591
        # renders them on the server, so the response already holds every
        # field the parser reads, the coordinate included
        # for backward compatibility
        settings.set('TWISTED_REACTOR', 'twisted.internet.asyncioreactor.AsyncioSelectorReactor', priority='spider')

        # 591 replies 403 to the default scrapy user agent, while it serves
        # requests without user agent just fine. Keep the one set by the
        # project, if there is any.
        user_agent = settings.get('USER_AGENT')
        if not user_agent or user_agent.startswith('Scrapy/'):
            settings.set('USER_AGENT', None, priority='spider')

