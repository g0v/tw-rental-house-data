# -*- coding: utf-8 -*-
# 範本設定檔。使用方式：
#
#   cp crawler/settings.sample.py crawler/settings.py
#   cp .env.example .env   # 再填入自己的值
#
# crawler/settings.py 與 .env 都已 gitignore。
# general_settings.py 是 committed 的禮貌預設值；個人環境（proxy／token／效能參數）
# 一律放 .env，由下面的環境變數覆蓋，不要直接改動並 commit 設定檔。

from .general_settings import *
import scrapy
import logging
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 只有環境變數有設值時才覆蓋 general_settings 的預設
if os.environ.get('TWRH_USER_AGENT'):
    USER_AGENT = os.environ['TWRH_USER_AGENT']

if os.environ.get('TWRH_ROBOTSTXT_OBEY'):
    ROBOTSTXT_OBEY = os.environ['TWRH_ROBOTSTXT_OBEY'] == '1'

if os.environ.get('TWRH_AUTOTHROTTLE'):
    AUTOTHROTTLE_ENABLED = os.environ['TWRH_AUTOTHROTTLE'] == '1'

if os.environ.get('TWRH_DOWNLOAD_DELAY'):
    DOWNLOAD_DELAY = float(os.environ['TWRH_DOWNLOAD_DELAY'])

if os.environ.get('TWRH_CONCURRENT_REQUESTS'):
    CONCURRENT_REQUESTS = int(os.environ['TWRH_CONCURRENT_REQUESTS'])

_proxy = os.environ.get('TWRH_PROXY')
if _proxy:
    DOWNLOADER_MIDDLEWARES = {
        **globals().get('DOWNLOADER_MIDDLEWARES', {}),
        'rotating_proxies.middlewares.RotatingProxyMiddleware': 610,
        'rotating_proxies.middlewares.BanDetectionMiddleware': 620,
    }
    ROTATING_PROXY_LIST = [_proxy]
    PLAYWRIGHT_LAUNCH_OPTIONS = {
        'proxy': {'server': _proxy}
    }

if os.environ.get('TWRH_BROWSER_INIT_SCRIPT'):
    BROWSER_INIT_SCRIPT = os.environ['TWRH_BROWSER_INIT_SCRIPT']

if os.environ.get('SENTRY_DSN'):
    SENTRY_DSN = os.environ['SENTRY_DSN']

# Enable debug log in all place
# scrapy.utils.log.configure_logging(install_root_handler=False)
# logging.basicConfig(
#     filename='scrapy.log',
#     format='%(levelname)s: %(message)s',
#     level=logging.DEBUG
# )
