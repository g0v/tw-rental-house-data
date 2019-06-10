# TW Rental House Utility for Scrapy

This package is built for crawling Taiwanese rental house related website using [Scrapy](https://scrapy.org/).
As behaviour of crawlers may differ from their goal, scale, and pipeline, this package provides only minimun feature set, which allow developer to list and decode a rental house webpage into structured data, without knowning too much about detail HTML and API structure of each website. In addition, this package is also designed for extensibility, which allow developers to insert customized callback, manipulate data, and integrate with existing crawler structure.

## Installation

## Basic Usage

## Handlers

## Contribution Guideline

Each spider class must:

1. Provide unit test
2. Runnable using scrapy command
3. Aviod unnecessary 3rd party dependency.
