# TW Rental House Utility for Scrapy

This package is built for crawling Taiwanese rental house related website using [Scrapy](https://scrapy.org/).
As behavior of crawlers may differ from their goal, scale, and pipeline, this package provides only minimum feature set, which allow developer to list and decode a rental house web page into structured data, without knowing too much about detail HTML and API structure of each website. In addition, this package is also designed for extensibility, which allow developers to insert customized callback, manipulate data, and integrate with existing crawler structure.

Although this package provide the ability to crawl rental house website, it's developer's responsibility to ensure crawling mechanism and usage of data. Please be friendly to target website, such as consider using [DOWNLOAD_DELAY](https://doc.scrapy.org/en/latest/topics/settings.html#std:setting-DOWNLOAD_DELAY) or [AUTO_THROTTLING](https://doc.scrapy.org/en/latest/topics/autothrottle.html) to prevent bulk requesting.

## Requirement

1. Python 3.10+
2. Playwright (for 591 spiders)
3. PaddleOCR (for 591 spiders)

## Installation

```bash
poetry add scrapy-tw-rental-house
```

### Install Playwright

We use Playwright default browser (Chromium) to render JavaScript content. Please install Playwright Chromium before using this package.

For more information, please refer to [official document](https://github.com/scrapy-plugins/scrapy-playwright)

```bash
poetry shell
playwright install chromium
```

### 591 specific

As 591 implements anti-crawler mechanism, it require additional setup to bypass it. To enable Playwright to bypass 591 anti-crawler mechanism, please ensure you 
get access to browser developer tool on browsing 591, and copy the setting to settings.py.

```python
BROWSER_INIT_SCRIPT = 'console.log("This command enable Playwright")'
```

### Enable OCR cache

As OCR is a time consuming process, we provide a cache mechanism to store OCR result. To enable OCR cache, please 
configure scrapy settings.py as following:

```python
# Enable OCR cache
OCR_CACHE_ENABLED = True # default false
OCR_CACHE_DIR = 'path/to/cache' # default to OCR_CACHE_DIR
```



## Basic Usage

This package currently support [591](http://rent.591.com.tw/). Each rental house website is a Scrapy Spider class. You can either crawl entire website using default setting , which will take couple days, or customize the behaviour base on your need.

The most basic usage would be creating a new Spider class that inherit Rental591Spider:

```python
from scrapy_twrh.spiders.rental591 import Rental591Spider

class MyAwesomeSpider(Rental591Spider):
    name='awesome'
```

And than start crawling by

```bash
scrapy crawl awesome
```

Please see [example](https://github.com/g0v/tw-rental-house-data/tree/master/scrapy-twrh-example) for detail usage.

## Items

All spiders populates 2 type of Scrapy items: `GenericHouseItem` and `RawHouseItem`.

`GenericHouseItem` contains normalized data field, spirders from different website will decode their data and fit into this schema in best effort.

`RawHouseItem` contains unnormalized data field, which keep original and structured data in best effort.

Note that both item are super set of schema. It developer's responsibility to check which field is provided when receiving an item.
For example, in `Rental591Spider`, for a single rental house, Scrapy will get:

1. 1x `RawHouseItem` + 1x `GenericHouseItem` during listing all houses, which provide only minimun data field for `GenericHouseItem`
2. 1x `RawHouseItem` + 1x `GenericHouseItem` during retrieving house detail.

## Handlers

All spiders in this package provide the following handlers:

1. `start_list`, similiar to `start_requests` in Scrapy, control how crawler issue search/list request to find all rental houses.
2. `parse_list`, similiar to `parse` in Scrapy, control how crawler handles response from `start_list` and generate request for detail house info page.
3. `parse_detail`, control how crawler parse detail page.

All spiders implements their own default handler, say, `default_start_list`, `default_parse_list`, and `default_parse_detail`, and can be overwrite during `__init__`. Please see [example](https://github.com/g0v/tw-rental-house-data/tree/master/scrapy-twrh-example) for how to control spider behavior using handlers.

