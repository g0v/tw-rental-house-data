# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Taiwan rental housing data (開放台灣民間租屋資料) - a monorepo that collects, processes, and publishes rental listing data from Taiwanese rental websites (primarily 591.com.tw). Licensed CC0 for open data.

Language: project docs and comments are primarily in Traditional Chinese (zh-TW).

## Repository Structure

| Package | Purpose | Stack |
|---|---|---|
| `scrapy-tw-rental-house/` | Core Scrapy spider package (published to PyPI as `scrapy-tw-rental-house`) | Python 3.10+, Poetry, Scrapy (plain HTTP, no browser) |
| `twrh-dataset/` | Full data pipeline: crawling, storage, export | Python 3.10+, Poetry, Django 5, PostgreSQL/GeoDjango |
| `scrapy-twrh-example/` | Example spiders showing package usage (local path dep on the core package) | Python, Poetry |
| `ui-next/` | Public website (rentalhouse.g0v.ddio.io) | Astro 7, Vue 3, Tailwind 4 |
| `csv-aggregator/` | Merge/dedup monthly CSV ZIPs into quarterly/yearly | Bash, Clickhouse local |

## First-Time Setup

### scrapy-tw-rental-house (core spider package)
```bash
cd scrapy-tw-rental-house
poetry install --with dev
```

### twrh-dataset (main data pipeline)
Requires PostgreSQL 15+ with PostGIS and the GeoDjango system libs (GDAL/GEOS/PROJ). The committed
`django/backend/settings.py` defaults to spatialite/sqlite — real deployments override it.
```bash
cd twrh-dataset
poetry install

# Config files are gitignored; create them locally
cp crawler/settings.sample.py crawler/settings.py   # reads per-env overrides from .env
cp .env.example .env                                # 全部設定都在這：DB（TWRH_DB_*）、proxy / UA / perf、
                                                    # SENTRY_DSN、SLACK_WEBHOOK_URL（settings_local.py 已退場）

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
poetry run scrapy crawl deal591 -L INFO -a lookback_days=2      # #229 deals stage：走 591「已成交」列表產成交事件；回補時開大 lookback

# flow runner（arch 3-2）：一份 stage 定義跑整條 pipeline，--from 從任一 stage 續跑；
# 完成判據＝artifact（rawpack 日包／manifest）或 logs/flow/<date>/ stamp 檔。
# go.sh／orchestrate.sh 仍是 production 路徑，flow 於 AWS 驗過後（D6）退役兩者
poetry run python flow.py run [--date YYYY-MM-DD] [--from STAGE] [--executor local|ecs] [--append]
poetry run python flow.py status [--date YYYY-MM-DD]

# Django management commands (all under django/, not backend/ as the README says)
poetry run python django/manage.py queuefinalize       # 1-1 收工鐵律 seeds==terminals；紅→exit 1＋Slack；附終結列滾動清理（90d）
poetry run python django/manage.py synthts             # L-C diff 模式：合成被 skip 物件的當日 HouseTS（標 is_synthesized）
poetry run python django/manage.py syncstateful -ts    # sync deal status into time-series
poetry run python django/manage.py manifest            # 1-2：產 manifests/<date>/{list,detail,snapshot}.json（--from/--to --source backfill 可回補）
poetry run python django/manage.py qualitycheck        # 1-2：quality/assertions.yaml × manifest 斷言，單一 Slack 通道
poetry run python django/manage.py statscheck          # generate stats, notify Slack（平行週後由 qualitycheck 取代）
poetry run python django/manage.py distcheck           # 當日分佈不變量（平行週後由 qualitycheck 取代）
poetry run python django/manage.py rawpack --reconcile # 3-1：當日 raw scratch 打成 raws/<vendor>/<date>.tar.zst＋index；--reconcile 抽樣比對 DB
poetry run python django/manage.py export -p           # periodic export (month-end only)
poetry run python django/manage.py export --help       # manual export: -f/-t dates, -u, -j, -b6
poetry run python django/manage.py monthreport         # 月報 quality gate：疊 manifest 出月窗（0=綠、2=紅）
poetry run python django/manage.py invalidate          # flag suspicious/unstable listing data
poetry run python django/manage.py archivehistory      # archive old HouseTS/HouseEtc to tar
poetry run python django/manage.py rawoffload <dir>    # pack raw HTML beyond 90d out of DB (dry-run unless --commit)
poetry run python django/manage.py deduprequest        # drop duplicate rows in request_ts

# 離線／重放工具（arch 3-3／3-1）
poetry run python tools/quality_offline.py --date …    # 無 DB 跑斷言引擎（sync 回 manifests/ 即可）
poetry run python tools/rerun_from_raws.py --from … --to …  # 從 raw 日包重放 detail parser（--commit 寫回；取代已失效的 rerun_detail_raw/dict）
./tools/sync-dev-data.sh                               # 成員用：拉 manifests/＋近 N 天 raw 日包（需 bucket 讀權限）
```

### ui-next (frontend)
Node 24 (`.nvmrc`).
```bash
cd ui-next
npm install
npm run dev                   # Astro dev server
npm run build                 # Static build to dist/ (gh-pages deploy)
npm run check                 # astro check (type check, also run in CI)
node scripts/check-urls.mjs   # URL 保留清單驗收（CI 會擋，改路由前先跑）
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

`twrh-dataset` has the B-layer queue test matrix (arch 2-3，與 1-1 同做)：
`django/crawlerrequest/tests.py` — 認領/釋放/batch/seed/狀態機/斷言引擎，
needs PostGIS（吃 `.env` 的 `TWRH_DB_*`，test DB 自動建立）：

```bash
cd twrh-dataset
poetry run python django/manage.py test crawlerrequest
```

其餘 `django/*/tests.py` are empty stubs；spider 行為驗證仍是 manual，
by running spiders against small real datasets.

### Dev/Test Workflow for scrapy-tw-rental-house

When a change touches `scrapy-tw-rental-house/`:

1. Make changes in `scrapy-tw-rental-house/scrapy_twrh/`.
2. Spot-check with the `twrh` CLI (plain HTTP, no DB needed).
   It is installed into the twrh-dataset venv by `./dev-core.sh` (see below):
   ```bash
   cd twrh-dataset
   poetry run twrh parse <saved-detail.html>       # offline: run parser on a saved page
   poetry run twrh detail <house-id>               # fetch + parse one detail page
   poetry run twrh list 金門縣                      # fetch + parse one list page
   poetry run twrh deals 台北市 --lookback 2        # walk the 已成交 list, print deal events (#229)
   poetry run twrh survey 金門縣 --save-html        # full city sweep → completeness report
   poetry run twrh harvest 花蓮縣                   # stratified fixture harvest + manifest
   poetry run twrh probe 花蓮縣 --baseline scrapy-tw-rental-house/baselines/hualien-fill-rate.json
                                                   # ratio assertions + exit code (nightly entry)
   ```
   `survey` reports list/detail success rates, property_type distribution, and per-field fill
   rates — compare against the previous report to catch silent field loss. `harvest` samples
   per parser branch (property/contact/price/floor strata) and saves fixture-candidate HTML with
   a manifest; 花蓮縣 covers far more strata than 金門縣. No DB writes. `probe` is the
   assertion version of survey (list volume, 200 rate, parse rate, legacy-template sentinel,
   fill-rate drift vs the committed baseline in `scrapy-tw-rental-house/baselines/`);
   `scrapy-tw-rental-house/nightly.sh` bundles pytest + probe — run manually for now
   (no local cron; production nightly comes later).
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

The offline pytest suite runs on scrubbed fixtures under `scrapy-tw-rental-house/tests/fixtures/`
(sockets blocked; see `tests/fixtures/README.md` for the prune/scrub strategy and known gaps).
The trial project (`scrapy-tw-rental-house/trial/`, not in git) predates the CLI; its
`detail-archive/` holds 431 pre-2026 detail pages in the old template, which the current parser
refuses (`LegacyTemplateError`) — parse those with a pre-2026 package release if ever needed.

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
3. `deal591` spider (#229, deals stage) walks each city's 已成交 list (`list?shType=clinch`,
   newest deal first, 50/page with a 30-row page step so adjacent pages overlap by 20) down to
   `lookback_days` and emits one DEAL item per known house with 591's own deal date and
   「N天成交」 as `n_day_deal`. Since the 2026 redesign a dealt listing's detail page is a 404,
   so this is the **only** deal signal; houses never seen by list are counted, not created.
4. `CrawlerPipeline` (the only item pipeline) stores items via Django ORM into PostgreSQL.
5. `syncstateful -ts` derives deal status / `n_day_deal` from the time series for houses the
   crawler only flagged; rows that already carry vendor-provided `deal_time` + `n_day_deal`
   (the deals stage) are copied as-is.
6. `statscheck` writes `Stats` rows and posts a summary to Slack (errors also go to Sentry).
7. `export -p` writes `[YYYYMM][CSV][Raw] TW-Rental-Data.zip` into `twrh-dataset/datas/`.
8. `csv-aggregator` merges monthly ZIPs into quarterly/yearly ones.
9. ZIPs are published to S3 (`https://twrh.s3.ap-northeast-3.amazonaws.com/<year>/…`); `ui-next`
   links to them via `ui-next/src/lib/download.ts`.

### Spider design (scrapy-tw-rental-house)
- `RentalSpider` (abstract) defines the contract; concrete spiders override
  `default_start_list` / `default_parse_list` / `default_parse_detail` and the
  `gen_*_request_args` methods. Callers can inject `start_list=`, `parse_list=`, `parse_detail=`
  into `__init__` to decorate default behaviour — this is how `twrh-dataset` and the examples
  customize crawling instead of subclassing parse logic.
- `Rental591Spider = ListMixin + DetailMixin` (both on top of `RequestGenerator`). Its
  `update_settings` pins the asyncio reactor (backward compatibility) and sets `USER_AGENT` to
  `None` unless the project chose its own — 591 403s the scrapy default UA but serves UA-less
  requests fine.
- Two item types per house per stage: `GenericHouseItem` (normalized schema) and `RawHouseItem`
  (raw HTML + parsed dict). Both are supersets — always check field presence before use.
- **Both list and detail requests are plain HTTP** — 591 renders pages on the server since its
  2026 redesign (no playwright, no browser, no init-script token). There is deliberately no
  fallback for being blocked yet; the 2.5-2 measurement in `docs/dx-roadmap.md` decides its shape.
- `detail_raw_parser.py` tracks **only the template 591 serves today** and is edited in place on
  redesigns; parsers for past templates live in git history / released packages. A pre-2026 page
  (detected via `LEGACY_MARKERS`, e.g. `wc-obfuscate-c-*`) is refused with `LegacyTemplateError`
  instead of parsing empty. OCR was removed with the legacy parser (dx 4-5); the coordinate is
  read from the nuxt init script (`positionRound`).
- Other 591 fragility handled in `rental591/util.py`: `reorder_inline_flex_dom` un-shuffles
  CSS-`order`-scrambled digits, `SimpleNuxtInitParser` extracts values from the Nuxt init script
  by regex.
- Region data: `scrapy_twrh/spiders/tw_regions.json` + `enums.py`. Enum members use Chinese names
  and **fixed integer values that appear in published datasets** — append new members, never
  renumber existing ones.

### Persistent crawl queue (twrh-dataset)
`crawler/spiders/persist_queue.py` is the reason crawls are resumable and why the pipeline is
date-keyed:
- Every request is a `RequestTS` row keyed by (year, month, day, hour, vendor, request_type)，
  帶顯式狀態機（arch 1-1）：`pending → in_flight → done | failed(n) | dead`。errback／parse error
  必寫終結狀態（failed 可重試、達 `TWRH_QUEUE_MAX_ATTEMPTS`（3）轉 dead）；「刪列＝完成」已廢除。
  收工鐵律＝`queuefinalize`：`done + dead == seeds` 且無殘留，紅→pipeline 中止；終結列保留 90 天
  （`TWRH_QUEUE_RETENTION_DAYS`，清理併在 queuefinalize）。
- At most `queue_length` (30) requests live in memory; `next_request()` claims one row atomically
  with raw SQL (`FOR UPDATE SKIP LOCKED` + `RETURNING`，`status→in_flight`、`attempts+1`)，
  so multiple spider processes can share a queue.
- `detail591 -a batch_size=N` stops after N completions and logs `Batch limit reached`. `go.sh`
  loops on that string, restarting the spider until it exits without it — this bounds memory over a
  multi-hour detail crawl. Overall progress survives restarts via
  `logs/progress/<YYYY-MM-DD>.detail.json` (`ProgressTracker.init_overall`).
- `--append` mode: list spider always regenerates seeds; detail spider only picks houses never
  detail-crawled (`etc.detail_raw IS NULL` — `monthly_price` can't tell since the 2026 redesign).
- Detail seeding has two modes: `full`（default，全量 OPENED）and `diff`
  （`TWRH_DETAIL_SEED_MODE=diff`，L-C list-diff skip 降頻：stale/指紋變/連續≥2天缺席/回列
  才入 queue，之後 `synthts` 合成被 skip 者的當日 HouseTS）。發布語意拍板前 production 走 full。
- List pagination（package 端）不信 591 的 `total_page`：宣稱頁範圍當下限，前緣逐頁探測
  直到空結果頁收單；statscheck 的「list 完整度」哨兵（`Stats.n_open_in_list`）監控捕獲率。
- `--start-early`: when run at/after 22:00, bucket the data under tomorrow's date.

### TWRH_TARGET_DATE
`go.sh` exports `TWRH_TARGET_DATE=YYYY-MM-DD` and pins it for the whole run so a crawl that spans
midnight doesn't split across two date buckets. It is read by `rental.models` (the `current_*`
time-series defaults), `crawler/utils.now_tuple`, `persist_queue`, `syncstateful`, and `statscheck`.
Set it manually (or use `go.sh --date`) when re-running part of a pipeline for a past day.
`export` honours it too (fixed 2026-08-28; it used to always take the real current date).

### Django models (twrh-dataset)
- `House` — current state of each listing, unique on (vendor, vendor_house_id).
- `HouseTS` — daily snapshot, unique on (year, month, day, hour, vendor, vendor_house_id). `hour` is
  currently always 0 (`current_stepped_hour` steps by 24).
- `HouseEtc` — 1:1 with `House`, holds `list_raw` / `detail_raw` HTML and `detail_dict`.
- `RequestTS` / `Stats` (crawlerrequest app) — crawl queue and per-run statistics.
- GeoDjango `PointField` (WGS84 / SRID 4326) for `rough_coordinate`.
- Deal status is sticky: once a house is `DEAL`, the pipeline will not overwrite it with `NOT_FOUND`.
- `RequestTS.request_type` has three values: `LIST` / `DETAIL` / `DEAL`; queuefinalize's zero-seed
  rule applies to list/detail only (a day without a deals run is legal), residue rules to all.
- Raw HTML 雙寫中（arch 3-1）：`HouseEtc` 照存（cutover 前），pipeline 同步落
  `raws/scratch/`，收尾 `rawpack` 打成 `raws/<vendor>/<date>.tar.zst`＋index。修完 parser bug 後
  用 `tools/rerun_from_raws.py` 對日包重放、**不需重爬**（舊 `rerun_detail_raw/dict.py` 已因
  改組失效，勿用）。

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
- Commit per task, autonomously: when a task (e.g. a roadmap item) is done, commit it right
  away with path-scoped `git add <files of that task>` — don't accumulate multi-task diffs
  or wait for confirmation (standing authorization, 2026-08-28).
- Never sweep in unrelated or user-owned untracked files (e.g. `cheatsheet.md`,
  `twrh-dataset/tw-rental-data/`); stage explicitly, never `git add -A`.

## CI/CD
- `.github/workflows/ui-deploy.yml` builds `ui-next/` (`npm run build` + URL 保留清單驗收) and
  deploys `ui-next/dist` to gh-pages on push to master.
- `.github/workflows/ui-next-pull-request.yml` runs `astro check` + build + URL 驗收 on `ui-next/` PRs.
- `.github/workflows/python-tests.yml` runs the offline pytest suite of `scrapy-tw-rental-house/`
  on pushes/PRs touching that package. Live probes stay out of public CI by design.
- `.github/workflows/dataset-tests.yml` runs the `twrh-dataset` queue test matrix against a
  PostGIS service container on pushes/PRs touching `twrh-dataset/`.
