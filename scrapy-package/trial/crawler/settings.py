# shared setting across different environment
# can be override by settings
import sys
import os
import scrapy
import logging

# Use latest code
sys.path.append('{}/../..'.format(
  os.path.dirname(os.path.realpath(__file__)))
)

scrapy.utils.log.configure_logging(install_root_handler=False)
logging.basicConfig(
    filename='scrapy.log',
    format='%(levelname)s: %(message)s',
    level=logging.DEBUG
)

BOT_NAME = 'scrapy-tw-rental-house-tester'
FEED_FORAMT = 'jsonlines'

# Obey robots.txt rules
ROBOTSTXT_OBEY = True

SPIDER_MODULES = ['crawler.spiders']
NEWSPIDER_MODULE = 'crawler.spiders'

# Need to be aware of meta redirect to avoid unnecessary download
METAREFRESH_ENABLED = False

# cookiejar are sometimes too smart....
COOKIES_ENABLED = False

# Configure item pipelines
# See https://doc.scrapy.org/en/latest/topics/item-pipeline.html
ITEM_PIPELINES = {
    'crawler.pipelines.CrawlerPipeline': 300
}

EXTENSIONS = {
}

# Enable and configure the AutoThrottle extension (disabled by default)
# See https://doc.scrapy.org/en/latest/topics/autothrottle.html
AUTOTHROTTLE_ENABLED = True
# The initial download delay
AUTOTHROTTLE_START_DELAY = 2
# The maximum download delay to be set in case of high latencies
AUTOTHROTTLE_MAX_DELAY = 60
# The average number of requests Scrapy should be sending in parallel to
# each remote server
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
# Enable showing throttling stats for every response received:
#AUTOTHROTTLE_DEBUG = False

# Issue #21, ensure request/sec <= 1
DOWNLOAD_DELAY = 1
