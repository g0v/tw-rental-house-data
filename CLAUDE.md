# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Taiwan rental housing data (開放台灣民間租屋資料) - a monorepo that collects, processes, and publishes rental listing data from Taiwanese rental websites (primarily 591.com.tw). Licensed CC0 for open data.

Language: project docs and comments are primarily in Traditional Chinese (zh-TW).

## Repository Structure

| Package | Purpose | Stack |
|---|---|---|
| `scrapy-tw-rental-house/` | Core Scrapy spider package (published to PyPI as `scrapy-tw-rental-house`) | Python 3.10+, Poetry, Scrapy, Playwright, PaddleOCR |
| `twrh-dataset/` | Full data pipeline: crawling, storage, export | Python 3.10+, Poetry, Django 5, PostgreSQL/GeoDjango |
| `scrapy-twrh-example/` | Example spiders showing package usage (local path dep on the core package) | Python, Poetry |
| `ui/` | Public website (rentalhouse.g0v.ddio.io) | Nuxt.js 2, Vue 2, Buefy |
| `csv-aggregator/` | Merge/dedup monthly CSV ZIPs into quarterly/yearly | Bash, Clickhouse local |

## First-Time Setup

### scrapy-tw-rental-house (core spider package)
```bash
cd scrapy-tw-rental-house
poetry install
poetry run playwright install chromium
```

### twrh-dataset (main data pipeline)
Requires PostgreSQL 15+ with PostGIS and the GeoDjango system libs (GDAL/GEOS/PROJ). The committed
`django/backend/settings.py` defaults to spatialite/sqlite — real deployments override it.
```bash
cd twrh-dataset
poetry install
poetry run playwright install chromium

# Config files are gitignored; create them locally
cp crawler/settings.sample.py crawler/settings.py   # reads per-env overrides from .env
cp .env.example .env                                # proxy / UA / token / perf knobs
vim django/backend/settings_local.py                # DATABASES, SENTRY_DSN, SLACK_WEBHOOK_URL

poetry run python django/manage.py migrate
poetry run python django/manage.py loaddata vendors   # required: pipeline looks up Vendor by name
```

## Common Commands

### twrh-dataset
```bash
# Full crawl pipeline (list -> detail -> sync -> stats -> export)
./go.sh [--append] [--start-early] [--date YYYY-MM-DD]
./gobg.sh [same flags]     # detached via setsid, logs to ../logs/<ts>.go.log

# Individual spiders
poetry run scrapy crawl list591 -L INFO
poetry run scrapy crawl detail591 -L INFO -a batch_size=2000

# Django management commands (all under django/, not backend/ as the README says)
poetry run python django/manage.py syncstateful -ts    # sync deal status into time-series
poetry run python django/manage.py statscheck          # generate stats, notify Slack
poetry run python django/manage.py export -p           # periodic export (month-end only)
poetry run python django/manage.py export --help       # manual export: -f/-t dates, -u, -j, -b6
poetry run python django/manage.py invalidate          # flag suspicious/unstable listing data
poetry run python django/manage.py archivehistory      # archive old HouseTS/HouseEtc to tar
poetry run python django/manage.py deduprequest        # drop duplicate rows in request_ts
```

### ui (frontend)
Node 16 (`.nvmrc`); note CI still pins Node 14.
```bash
cd ui
npm install
npm run dev        # Dev server with hot reload
npm run generate   # Static site generation (for gh-pages deploy)
npm run lint       # ESLint (the only automated check in CI)
```

### csv-aggregator
Needs `clickhouse local` on PATH.
```bash
./merge-and-dedup.sh <source-dir-of-monthly-raw-zips> <prefix e.g. 2025Q1>
./dedup-single.sh "<path to [YYYYMM][CSV][Raw] TW-Rental-Data.zip>"
./check.sh <zip-or-csv>   # verify CSV/JSON counts, inject 編碼表
```

## Testing

`scrapy-tw-rental-house` has an offline pytest suite (`scrapy-tw-rental-house/tests`):

```bash
cd scrapy-tw-rental-house
poetry install --with dev
poetry run pytest
```

`twrh-dataset` has none — `django/*/tests.py` are empty stubs, and verification there is manual,
by running spiders against small real datasets.

### Dev/Test Workflow for scrapy-tw-rental-house

When a change touches `scrapy-tw-rental-house/`:

1. Make changes in `scrapy-tw-rental-house/scrapy_twrh/`.
2. Spot-check with the `twrh` CLI (plain HTTP, no DB / playwright / BROWSER_INIT_SCRIPT needed).
   It is installed into the twrh-dataset venv by `./dev-core.sh` (see below):
   ```bash
   cd twrh-dataset
   poetry run twrh parse <saved-detail.html>       # offline: run parser on a saved page
   poetry run twrh detail <house-id>               # fetch + parse one detail page
   poetry run twrh list 金門縣                      # fetch + parse one list page
   poetry run twrh survey 金門縣 --save-html        # full city sweep → completeness report
   ```
   `survey` reports list/detail success rates, property_type distribution, and per-field fill
   rates — compare against the previous report to catch silent field loss. No DB writes.
3. To run the real pipeline against local core changes, link it in editable mode
   (revert with `poetry install --sync`):
   ```bash
   cd twrh-dataset
   ./dev-core.sh
   ```
4. Test via `scrapy-twrh-example` (local path dep, picks up changes automatically):
   ```bash
   cd scrapy-twrh-example
   poetry install
   poetry run scrapy crawl singleCity -a city="金門縣" -L INFO   # small dataset
   poetry run scrapy crawl singleCity -a city="花蓮縣" -L INFO   # larger dataset
   ```
5. Review `scrapy.log` and console output for errors/warnings.

The trial project (`scrapy-tw-rental-house/trial/`, not in git) predates the CLI; its
`detail-archive/` still holds 431 pre-2026 detail pages useful as old-format parse fixtures.

### Publishing the core package

Use the `/publish-scrapy-twrh` skill. It bumps `scrapy-tw-rental-house/pyproject.toml`, runs
`poetry build && poetry publish`, then bumps the `scrapy-tw-rental-house` version in
`twrh-dataset/pyproject.toml` and runs `poetry update`. `twrh-dataset` consumes the **published**
package, so local core changes are not visible there until a release — unless you linked the
local core with `twrh-dataset/dev-core.sh` (editable install; check `pip show scrapy-tw-rental-house`
and revert with `poetry install --sync` before publishing or crawling for real).

`scrapy-tw-rental-house/scrapy_tw_rental_house` is a committed **symlink** to `scrapy_twrh` that
Poetry needs to pick up the package (name-derived) and that preserves the legacy import path. Don't
delete or replace it with a copy.

## Architecture

### Data flow
1. `list591` spider walks 591 search pages per city, sorted by post date, writing `House`/`HouseTS`
   rows plus one detail request per listing.
2. `detail591` spider crawls each open listing's detail page.
3. `CrawlerPipeline` (the only item pipeline) stores items via Django ORM into PostgreSQL.
4. `syncstateful -ts` derives deal status / `n_day_deal` and pushes it into the time series.
5. `statscheck` writes `Stats` rows and posts a summary to Slack (errors also go to Sentry).
6. `export -p` writes `[YYYYMM][CSV][Raw] TW-Rental-Data.zip` into `twrh-dataset/datas/`.
7. `csv-aggregator` merges monthly ZIPs into quarterly/yearly ones.
8. ZIPs are published to S3 (`https://twrh.s3.ap-northeast-3.amazonaws.com/<year>/…`); `ui` links to
   them via `ui/libs/defs.js` `S3_BASE`.

### Spider design (scrapy-tw-rental-house)
- `RentalSpider` (abstract) defines the contract; concrete spiders override
  `default_start_list` / `default_parse_list` / `default_parse_detail` and the
  `gen_*_request_args` methods. Callers can inject `start_list=`, `parse_list=`, `parse_detail=`
  into `__init__` to decorate default behaviour — this is how `twrh-dataset` and the examples
  customize crawling instead of subclassing parse logic.
- `Rental591Spider = ListMixin + DetailMixin` (both on top of `RequestGenerator`). It forces the
  scrapy-playwright download handlers and the asyncio reactor via `update_settings`.
- Two item types per house per stage: `GenericHouseItem` (normalized schema) and `RawHouseItem`
  (raw HTML + parsed dict). Both are supersets — always check field presence before use.
- **List requests are plain HTTP; only detail requests run through Playwright** (`playwright: True`
  in request meta, with `open_map` page method to reveal coordinates).
- 591 obfuscates price / floor / area in the detail page as base64 images inside
  `<wc-obfuscate-c-price|c-floor|c-area>` elements. `detail_raw_parser.parse_obfuscate_fields` runs
  **PaddleOCR** on them (`ocr_utils.py`). This is field de-obfuscation, not CAPTCHA solving. OCR
  results are cached on disk by image hash (`ocr_cache/`, sharded), controlled by
  `OCR_CACHE_ENABLED` / `OCR_CACHE_DIR`.
- `PlaywrightUtils.init_page` blocks images/CSS and `BROWSER_SKIP_DOMAINS`, and disk-caches JS
  (`BROWSER_JS_CACHE_ENABLED`, `js_cache/`). `BROWSER_INIT_SCRIPT` must be set for 591 pages to
  render — copy it from a real browser session.
- Other 591 fragility handled in `rental591/util.py`: `reorder_inline_flex_dom` un-shuffles
  CSS-`order`-scrambled digits, `SimpleNuxtInitParser` extracts values from the Nuxt init script
  by regex.
- Region data: `scrapy_twrh/spiders/tw_regions.json` + `enums.py`. Enum members use Chinese names
  and **fixed integer values that appear in published datasets** — append new members, never
  renumber existing ones.

### Persistent crawl queue (twrh-dataset)
`crawler/spiders/persist_queue.py` is the reason crawls are resumable and why the pipeline is
date-keyed:
- Every pending request is a `RequestTS` row keyed by (year, month, day, hour, vendor, request_type).
  Completing a request **deletes** the row; leftover rows are failures (`statscheck` counts them).
- At most `queue_length` (30) requests live in memory; `next_request()` claims one row atomically-ish
  with raw SQL setting `owner = spider_id`, so multiple spider processes can share a queue.
- `detail591 -a batch_size=N` stops after N completions and logs `Batch limit reached`. `go.sh`
  loops on that string, restarting the spider until it exits without it — this bounds memory over a
  multi-hour detail crawl. Overall progress survives restarts via
  `logs/progress/<YYYY-MM-DD>.detail.json` (`ProgressTracker.init_overall`).
- `--append` mode: list spider always regenerates seeds; detail spider only picks houses with
  `monthly_price IS NULL`.
- `--start-early`: when run at/after 22:00, bucket the data under tomorrow's date.

### TWRH_TARGET_DATE
`go.sh` exports `TWRH_TARGET_DATE=YYYY-MM-DD` and pins it for the whole run so a crawl that spans
midnight doesn't split across two date buckets. It is read by `rental.models` (the `current_*`
time-series defaults), `crawler/utils.now_tuple`, `persist_queue`, `syncstateful`, and `statscheck`.
Set it manually (or use `go.sh --date`) when re-running part of a pipeline for a past day.
Caveat: `export` does **not** honour it — it always uses the real current date.

### Django models (twrh-dataset)
- `House` — current state of each listing, unique on (vendor, vendor_house_id).
- `HouseTS` — daily snapshot, unique on (year, month, day, hour, vendor, vendor_house_id). `hour` is
  currently always 0 (`current_stepped_hour` steps by 24).
- `HouseEtc` — 1:1 with `House`, holds `list_raw` / `detail_raw` HTML and `detail_dict`.
- `RequestTS` / `Stats` (crawlerrequest app) — crawl queue and per-run statistics.
- GeoDjango `PointField` (WGS84 / SRID 4326) for `rough_coordinate`.
- Deal status is sticky: once a house is `DEAL`, the pipeline will not overwrite it with `NOT_FOUND`.
- Because `HouseEtc` keeps raw HTML, `tools/rerun_detail_raw.py` and `tools/rerun_detail_dict.py`
  can re-parse historical listings through the current parser **without re-crawling** — use these
  after fixing a detail-parsing bug.

### Scrapy settings layering (twrh-dataset)
- `crawler/general_settings.py` — committed, shared. Calls `django.setup()` (adds `django/` to
  `sys.path`, sets `DJANGO_ALLOW_ASYNC_UNSAFE`), registers `CrawlerPipeline` and the Sentry
  extension, and sets the polite defaults: `ROBOTSTXT_OBEY=True`, `AUTOTHROTTLE_ENABLED=True`,
  `DOWNLOAD_DELAY=1`, `COOKIES_ENABLED=False`, `METAREFRESH_ENABLED=False`.
- `crawler/settings.py` — **gitignored**, per-environment, `import *`s the above and overrides it.
  The production copy on the crawl host turns the polite defaults off (`ROBOTSTXT_OBEY=False`,
  `AUTOTHROTTLE_ENABLED=False`, `DOWNLOAD_DELAY=0`, high `CONCURRENT_REQUESTS`) and routes through
  a local rotating proxy. Don't assume the committed defaults are what actually runs; check the
  local file. `detail591` disables the rotating-proxy middleware via `custom_settings`.

## Git Workflow
- Never run `git add` automatically. Let the user decide what to stage.
- When committing, if nothing is staged, warn the user instead of proceeding.

## CI/CD
- `.github/workflows/ui-deploy.yml` builds `ui/` with `npm run generate` and deploys `ui/dist` to
  gh-pages on push to master.
- `.github/workflows/ui-pull-request.yml` runs ESLint on `ui/`.
- Nothing in CI touches the Python packages or the data pipeline.
