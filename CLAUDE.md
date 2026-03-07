# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Taiwan rental housing data (開放台灣民間租屋資料) - a monorepo that collects, processes, and publishes rental listing data from Taiwanese rental websites (primarily 591.com.tw). Licensed CC0 for open data.

Language: project docs and comments are primarily in Traditional Chinese (zh-TW).

## Repository Structure

| Package | Purpose | Stack |
|---|---|---|
| `scrapy-tw-rental-house/` | Core Scrapy spider package (published to PyPI) | Python 3.10+, Poetry, Scrapy, Playwright, PaddleOCR |
| `twrh-dataset/` | Full data pipeline: crawling, storage, export | Python 3.10+, Poetry, Django 5, PostgreSQL/GeoDjango |
| `scrapy-twrh-example/` | Example spiders showing package usage | Python, Poetry |
| `ui/` | Public website (rentalhouse.g0v.ddio.io) | Nuxt.js 2, Vue 2, Buefy |
| `csv-aggregator/` | CSV merge/dedup utility | Bash, Clickhouse local |

## Common Commands

### scrapy-tw-rental-house (core spider package)
```bash
cd scrapy-tw-rental-house
poetry install
poetry run playwright install chromium
```

### twrh-dataset (main data pipeline)
```bash
cd twrh-dataset
poetry install

# Run full crawl pipeline (list -> detail -> sync -> stats -> export)
./go.sh [--append] [--start-early]

# Individual spiders
poetry run scrapy crawl list591 -L INFO
poetry run scrapy crawl detail591 -L INFO

# Django management commands
poetry run python django/manage.py syncstateful -ts    # Sync time-series
poetry run python django/manage.py statscheck          # Generate stats, notify Slack
poetry run python django/manage.py export -p           # Export CSV/JSON datasets
poetry run python django/manage.py invalidate          # Mark missing houses
poetry run python django/manage.py archivehistory      # Archive old snapshots
```

### ui (frontend)
```bash
cd ui
npm install
npm run dev        # Dev server with hot reload
npm run generate   # Static site generation (for gh-pages deploy)
npm run lint       # ESLint
```

## Dev/Test Workflow for scrapy-tw-rental-house

When a change touches `scrapy-tw-rental-house/`:

### 1. Development & Verification

1. Make changes in `scrapy-tw-rental-house/`
2. Smoke-test via the trial spider:
   ```bash
   cd scrapy-tw-rental-house/trial
   ./go.sh
   ```
3. Test via `scrapy-twrh-example` (uses local path dep, picks up changes automatically):
   ```bash
   cd scrapy-twrh-example
   poetry install
   poetry run scrapy crawl singleCity -a city="金門縣" -L INFO   # small dataset
   poetry run scrapy crawl singleCity -a city="花蓮縣" -L INFO   # larger dataset
   ```
4. Review console output for errors/warnings.


## Architecture

### Data Flow
1. `list591_spider` crawls rental listings sorted by post date
2. `detail591_spider` crawls individual listing details
3. `CrawlerPipeline` stores items via Django ORM into PostgreSQL
4. `syncstateful` updates time-series aggregations
5. `statscheck` sends Slack notifications
6. `export` generates CSV/JSON dataset files
7. `csv-aggregator` merges monthly ZIPs into quarterly/yearly

### Spider Design (scrapy-tw-rental-house)
- `RentalSpider` is the abstract base class; concrete spiders override `default_handler`, `start_list`, `parse_list`, `parse_detail`
- Two item types: `GenericHouseItem` (normalized schema) and `RawHouseItem` (raw preservation)
- Anti-crawler: Playwright for JS rendering, PaddleOCR for CAPTCHA bypass, OCR results cached by image hash
- Region data: `scrapy_twrh/tw_regions.json` defines top/sub regions

### Django Models (twrh-dataset)
- `House` - current rental listings, deduplicated by (vendor, vendor_house_id)
- `HouseTS` - time-series snapshots (year/month/day/hour partitioned)
- `HouseEtc` - raw/detail data blob storage
- Uses GeoDjango `PointField` (WGS84/SRID 4326) for coordinates
- Deal status is preserved: once marked DEAL, pipeline won't overwrite

### Key Configuration
- Scrapy: `AUTOTHROTTLE_ENABLED=True`, `DOWNLOAD_DELAY=1`, `COOKIES_ENABLED=False`, `ROBOTSTXT_OBEY=True`
- Django local settings: `twrh-dataset/django/backend/settings_local.py` (not committed)
- Sentry and Slack integrations configured via settings

## Git Workflow
- Never run `git add` automatically. Let the user decide what to stage.
- When committing, if nothing is staged, warn the user instead of proceeding.

## CI/CD
- GitHub Actions deploys `ui/` to gh-pages on push to master
- PR checks run ESLint on `ui/`
- Dependabot monitors npm and GitHub Actions dependencies
