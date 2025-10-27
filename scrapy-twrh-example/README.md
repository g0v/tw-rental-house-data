# Scrapy TW Rental House Example / 範例

This package illustrate all example usage of latest (main/master) `scrapy-tw-rental-house`.

## System requirement / 系統需求

1. Python 3.10+
2. [Poetry](https://python-poetry.org/)

## Installation / 安裝步驟

```bash
# Install package with poetry
poetry install
```

## Example 0 - Simplest usage / 直接用

This example uses all default setting.
Debug log can be access in scrapy.log

```bash
scrapy crawl simple -L INFO
```

## Example 1 - Specify city / 指定城市

This example specifies the big 6 cities on init.
Debug log can be access in scrapy.log

```bash
scrapy crawl big6 -L INFO
```

## Example 2 - Query only first 90 results / 只抓前 90 筆資料

This example retrieve first 90 results for each city.
Debug log can be access in scrapy.log

```bash
scrapy crawl first90 -L INFO
```

## Example 3 - Populate only location info / 只儲存位置資訊

This example ignores house item not containing location info. 
You can see the spirder doesn't populate any item until requesting location related page.

```bash
scrapy crawl location-only
```

## Example 4 - Single city with command line argument / 用命令列指定單一城市

This example allows you to specify a single city via command line argument.
The city name is validated against `TopRegionType` enum to ensure it's valid.

```bash
# Crawl data for Taipei City
scrapy crawl singleCity -a city="台北市"

# Crawl data for New Taipei City
scrapy crawl singleCity -a city="新北市"

# Crawl data for Kaohsiung City
scrapy crawl singleCity -a city="高雄市"
```
