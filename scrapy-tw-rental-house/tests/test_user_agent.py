from scrapy.settings import Settings

from scrapy_twrh.spiders.rental591 import Rental591Spider

def update_settings(**custom):
    settings = Settings()
    for name, value in custom.items():
        settings.set(name, value, priority='project')
    Rental591Spider.update_settings(settings)
    return settings

def test_drop_default_scrapy_user_agent():
    # 591 replies 403 to it, while it serves requests without one just fine
    assert update_settings().get('USER_AGENT') is None

def test_keep_user_agent_of_the_project():
    assert update_settings(USER_AGENT='my-crawler').get('USER_AGENT') == 'my-crawler'

def test_drop_empty_user_agent():
    assert update_settings(USER_AGENT='').get('USER_AGENT') is None
