# 範本設定檔。使用方式：
#
#   cp crawler/settings.sample.py crawler/settings.py
#   cp .env.example .env   # 再填入自己的值
#
# crawler/settings.py 與 .env 都已 gitignore，
# 個人環境的 proxy／token／效能參數請放 .env，不要 commit。
import sys
import os
import scrapy
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

scrapy.utils.log.configure_logging(install_root_handler=False)
logging.basicConfig(
    filename='scrapy.log',
    format='%(levelname)s: %(message)s',
    level=logging.INFO
)

LOG_LEVEL = 'INFO'
USER_AGENT = os.environ.get('TWRH_USER_AGENT') or None
FEED_FORAMT = 'jsonlines'

# Obey robots.txt rules
ROBOTSTXT_OBEY = False

SPIDER_MODULES = ['crawler.spiders']
NEWSPIDER_MODULE = 'crawler.spiders'

# Need to be aware of meta redirect to avoid unnecessary download
METAREFRESH_ENABLED = False

# cookiejar are sometimes too smart....
COOKIES_ENABLED = False

# Configure item pipelines
# See https://doc.scrapy.org/en/latest/topics/item-pipeline.html
ITEM_PIPELINES = {
  'crawler.pipelines.CrawlerPipeline': 300,
  'crawler.pipelines.CsvPipeline': 301
}

EXTENSIONS = {
}

# Enable and configure the AutoThrottle extension (disabled by default)
# See https://doc.scrapy.org/en/latest/topics/autothrottle.html
AUTOTHROTTLE_ENABLED = os.environ.get('TWRH_AUTOTHROTTLE', '1') == '1'

DOWNLOAD_DELAY = float(os.environ.get('TWRH_DOWNLOAD_DELAY', '1'))

CONCURRENT_REQUESTS = int(os.environ.get('TWRH_CONCURRENT_REQUESTS', '16'))

DOWNLOADER_MIDDLEWARES = {
    'rotating_proxies.middlewares.RotatingProxyMiddleware': 610,
    'rotating_proxies.middlewares.BanDetectionMiddleware': 620,
}

_proxy = os.environ.get('TWRH_PROXY')
if _proxy:
    ROTATING_PROXY_LIST = [_proxy]
    PLAYWRIGHT_LAUNCH_OPTIONS = {
        'proxy': {'server': _proxy}
    }

PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 1800000

PLAYWRIGHT_CONTEXTS = {
  "persistent": {
    "ignore_https_errors": True
  }
}

OCR_CACHE_ENABLED = True
OCR_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '../cache/ocr'
)


BROWSER_JS_CACHE_ENABLED = True
BROWSER_JS_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '../cache/js'
)

# 591 頁面要能 render 必須設定，值請自備（不可 commit，理由見 docs/dx-roadmap.md 架構原則）
BROWSER_INIT_SCRIPT = os.environ.get('TWRH_BROWSER_INIT_SCRIPT', 'console.log("Browser Init");')
