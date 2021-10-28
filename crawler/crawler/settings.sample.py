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
import os

# Enable sentry to catch all error
# SENTRY_DSN = 'https://your.sentry/dsn'

# Enable debug log in all place
# scrapy.utils.log.configure_logging(install_root_handler=False)
# logging.basicConfig(
#     filename='scrapy.log',
#     format='%(levelname)s: %(message)s',
#     level=logging.DEBUG
# )


# Crawl responsibly by identifying yourself (and your website) on the user-agent
# USER_AGENT = 'who-am-i (https://who.am.i.com)'

