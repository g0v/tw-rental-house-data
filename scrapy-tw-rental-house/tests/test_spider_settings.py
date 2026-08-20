from scrapy.settings import Settings

from scrapy_twrh.spiders.rental591 import Rental591Spider

MIDDLEWARE = 'scrapy_twrh.middlewares.PlaywrightFallbackMiddleware'

def update_settings(**custom):
    settings = Settings()
    for name, value in custom.items():
        settings.set(name, value, priority='project')
    Rental591Spider.update_settings(settings)
    return settings

def test_enable_fallback_middleware():
    assert MIDDLEWARE in update_settings().getdict('DOWNLOADER_MIDDLEWARES')

def test_keep_middleware_of_the_project():
    middlewares = update_settings(DOWNLOADER_MIDDLEWARES={
        'rotating_proxies.middlewares.RotatingProxyMiddleware': 610
    }).getdict('DOWNLOADER_MIDDLEWARES')

    assert middlewares['rotating_proxies.middlewares.RotatingProxyMiddleware'] == 610
    assert MIDDLEWARE in middlewares

def test_keep_middleware_order_of_the_project():
    middlewares = update_settings(DOWNLOADER_MIDDLEWARES={
        MIDDLEWARE: 999
    }).getdict('DOWNLOADER_MIDDLEWARES')

    assert middlewares[MIDDLEWARE] == 999

def test_download_by_playwright_handler():
    handlers = update_settings().getdict('DOWNLOAD_HANDLERS')

    assert handlers['https'] == \
        'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler'
