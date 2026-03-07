#!/bin/bash

# Ensure scrapy-tw-rental-house is up-to-date with local source
poetry update scrapy-tw-rental-house

echo '===== 591 ====='
poetry run scrapy crawl singleCity -a city=花蓮縣 -L INFO

