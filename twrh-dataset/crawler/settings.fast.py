# -*- coding: utf-8 -*-

# Scrapy settings for crawler project
#
# For simplicity, this file contains only settings considered important or
# commonly used. You can find more settings consulting the documentation:
#
#     https://doc.scrapy.org/en/latest/topics/settings.html
#     https://doc.scrapy.org/en/latest/topics/downloader-middleware.html
#     https://doc.scrapy.org/en/latest/topics/spider-middleware.html

from .general_settings import *
import scrapy
import logging

scrapy.utils.log.configure_logging(install_root_handler=False)
logging.basicConfig(
    filename='scrapy.log',
    format='%(levelname)s: %(message)s',
    level=logging.INFO
)

USER_AGENT = None
ROBOTSTXT_OBEY = False

# SENTRY_DSN = 'https://26de353dd288df788de37ab648f407ba@o190111.ingest.sentry.io/4506485023768576'


# DOWNLOADER_MIDDLEWARES = {
#     'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,
#     'scrapy_fake_useragent.middleware.RandomUserAgentMiddleware': 400,
# }

# PROXY_URL = "http://news-crawler-internal.askmiso.com:3333/"
# DOWNLOADER_MIDDLEWARES['crawler.proxy_middleware.ProxyMiddleware'] = 543

# Crawl responsibly by identifying yourself (and your website) on the user-agent
#USER_AGENT = 'crawler (+http://www.yourdomain.com)'

# Configure maximum concurrent requests performed by Scrapy (default: 16)
CONCURRENT_REQUESTS = 32

# Configure a delay for requests for the same website (default: 0)
# See https://doc.scrapy.org/en/latest/topics/settings.html#download-delay
# See also autothrottle settings and docs
DOWNLOAD_DELAY = 0
# The download delay setting will honor only one of:
# CONCURRENT_REQUESTS_PER_DOMAIN = 1
# CONCURRENT_REQUESTS_PER_IP = 1

AUTOTHROTTLE_ENABLED = False

PLAYWRIGHT_LAUNCH_OPTIONS = {
  "proxy": {
    "server": "http://localhost:8000"
  }
}

PLAYWRIGHT_MAX_CONTEXTS = 30
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 1200000

PLAYWRIGHT_CONTEXTS = {
  "persistent": {
    "ignore_https_errors": True
  }
}

ROTATING_PROXY_LIST = [
  "http://localhost:8000",
]
BROWSER_INIT_SCRIPT = 'window.__30f1fb31232ca3e80fba75ceb4253b35__ = true;'

DOWNLOADER_MIDDLEWARES = {
    'rotating_proxies.middlewares.RotatingProxyMiddleware': 610,
    'rotating_proxies.middlewares.BanDetectionMiddleware': 620,
}
