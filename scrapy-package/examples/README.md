# Scrapy TW Rental House Example / 範例

This folder illustrate all example usage of `scrapy_twrh`.

## Installation / 安裝步驟

```bash
cd examples
# Create python 3 virtual env
virtualenv -p /usr/bin/python3 .venv
# Enable virtual env
. .venv/bin/activate
# Install package
pip install scrapy-tw-rental-house --upgrade
```

## Example 0 - Simplest usage / 直接用

This example uses all default setting.
Debug log can be access in scrapy.log

```bash
cd basic
scrapy crawl simple -L INFO
```

## Example 1 - Specify city / 指定城市

This example specifies the big 6 cities on init.
Debug log can be access in scrapy.log

```bash
cd basic
scrapy crawl big6 -L INFO
```

## Example 2 - Query only first 90 results / 只抓前 90 筆資料

This example retrieve first 90 results for each city.
Debug log can be access in scrapy.log

```bash
cd basic
scrapy crawl first90 -L INFO
```

## Example 3 - Populate only location info / 只儲存位置資訊

This example ignores house item not containing location info. 
You can see the spirder doesn't populate any item until requesting location related page.

```bash
cd basic
scrapy crawl location-only
```

## Example 4 - Persist request / 另存網頁請求

`TODO`

```bash
# This example catch all detail info request and store for later use.
# See `persist-request/pipelines.py` for detail usage.
```
