# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Taiwan rental housing data (開放台灣民間租屋資料) - a monorepo that collects, processes, and publishes rental listing data from Taiwanese rental websites (primarily 591.com.tw). Licensed CC0 for open data.

Language: project docs and comments are primarily in Traditional Chinese (zh-TW).

## Repository Structure

| Package | Purpose | Stack |
|---|---|---|
| `scrapy-tw-rental-house/` | Core Scrapy spider package (published to PyPI as `scrapy-tw-rental-house`) | Python 3.10+, Poetry, Scrapy (plain HTTP, no browser) |
| `twrh-dataset/` | Full data pipeline: crawling, file partitions on S3, export | Python 3.10+, Poetry, Scrapy, pyarrow（no DB／Django since S6, 2026-10） |
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
No database: every stage reads and writes date-partitioned files (EFS/local dir + S3). Needs `zstd` on PATH.
```bash
cd twrh-dataset
poetry install

# Config files are gitignored; create them locally
cp crawler/settings.sample.py crawler/settings.py   # reads per-env overrides from .env
cp .env.example .env                                # proxy / UA / perf、SENTRY_DSN、SLACK_WEBHOOK_URL、
                                                    # TWRH_ARTIFACT_DIR／TWRH_RAW_DIR 等檔案位置
./tools/sync-dev-data.sh                            # 選用：拉 manifests／近 N 天分區與 raw 日包（需 bucket 讀權限）
```

## Common Commands

### twrh-dataset
```bash
# Full crawl pipeline（唯一編排：flow.py）
poetry run python flow.py run [--date YYYY-MM-DD] [--from STAGE] [--executor local|ecs] [--append] [--vendor 591] [--dry-run]
#   run stages：list→liststubs→snapshotfinal→latest→export→seed→detail→deals→queuefinalize→rawpack→parsed→dealevents→snapshot→manifest→quality→prune→logs
#   （snapshotfinal＝昨日 final snapshot 重摺，必須在 seed 之前：種子判準讀它；2026-09-19 首夜讀到 provisional 多播 3,625 戶）
#   （export 每月 1 日出上月，讀 snapshot 分區；只依賴上月最後一天的 final，所以緊接 latest、爬取之前——flow 中途被擋也有月包；
#     1 日 snapshotfinal 沒成功就印 !!! 拒跑，不拿 provisional 出貨，補法見 devop/aws/README.md「1 日 export 補跑」）
poetry run python flow.py sweep [--date YYYY-MM-DD] [--vendor 591] [--dry-run]   # 前緣掃描：busy→frontier→liststubs→newdetail→queuefinalize→rawpack→parsed→logs
poetry run python flow.py status [--date YYYY-MM-DD]                             # 日跑 stage 與各輪 sweep 的完成狀態
#   注意：flow 的 --date（預設今天）會蓋掉環境變數 TWRH_TARGET_DATE——本機重跑過去日一定帶 --date

# Individual spiders
poetry run scrapy crawl list591 -L INFO
poetry run scrapy crawl detail591 -L INFO -a batch_size=2000
poetry run scrapy crawl list591 -L INFO -a frontier_pages=30    # 前緣掃描：只走每縣市 list 最前面幾頁，整頁已知即收單（flow.py sweep）
poetry run scrapy crawl detail591 -L INFO -a seed_mode=new      # 只排今日在列、從未 detail 的 OPENED（前緣掃描的後半）
poetry run scrapy crawl deal591 -L INFO -a lookback_days=7      # #229 deals stage：走 591「已成交」列表產成交事件；591 成交後數日仍補列，日跑取 7；回補時再開大

# flow runner（arch 3-2）：完成判據＝artifact（rawpack 日包／manifest）或 logs/flow/<date>/ stamp 檔；
# sweep 各輪的 stamp 在 logs/flow/<date>/sweep-<HHMM>/。vendor 維度來自 crawler/vendor_profiles.py
#（spider 名、has_deals_stage、supports_frontier、頁數、lookback、sweep 速率；新 vendor＝加一個 dict）

# twrhctl（S6 起 scrapy 以外的唯一指令入口；python -m twrhctl 列出全部）
poetry run python -m twrhctl queuefinalize       # 收工鐵律 seeds==terminals（檔案 queue）；紅→exit 1＋Slack
poetry run python -m twrhctl queuebusy --vendor "591 租屋網"   # 同 vendor 同日 bucket 2h 內有 worker 心跳即 exit 1（flow sweep 互斥）
poetry run python -m twrhctl rawpack --reconcile # 當日 raw scratch 打成 raws/<vendor>/<date>.tar.zst＋index（同日多次 run＝與既有日包聯集）；--reconcile 報 member 數 vs queue done
poetry run python -m twrhctl artifactpack --tree list|parsed|deals   # scratch shards → artifacts/<tree>/<vendor>/<date>/<run>.{jsonl.zst,parquet}（＋S3）；一輪一檔、永不改寫別輪；--reupload 補傳
poetry run python -m twrhctl snapshotfold [--date] [--only final|provisional]  # 昨日 final＝fold(前日 snapshot, 昨日分區)（snapshotfinal stage，seed 前）、今日 provisional＝fold(昨日 final, 今日分區) → snapshot/<vendor>/<date>.parquet（一天一檔，final 覆寫 provisional）；前兩日都缺＝往回找最近一份逐日重放；--reupload
poetry run python -m twrhctl latestfold [--date] [--bootstrap --from D1 --to D2]  # S3c：總表(昨日)＝fold(總表(前日), 昨日 final) → latest/<vendor>/daily/<date>.parquet；每月 1 日另存 monthly/；兩邊依 id 排序串流合併，記憶體不隨總表列數長
poetry run python -m twrhctl manifest            # manifests/<date>/{list,detail,deals,snapshot}.json（由分區檔算，source: partitions）
poetry run python -m twrhctl qualitycheck        # quality/assertions.yaml × manifest 斷言，單一 Slack 通道（錯誤也進 Sentry）
poetry run python -m twrhctl localprune [--dry-run]  # EFS 清理（prune stage）：早於 7 天且 S3 同 key 同大小才刪；snapshot 留上月 1 日起（export 只讀本地）；不碰 queue
poetry run python -m twrhctl export -p           # periodic export：每月 1 日出上月（讀 snapshot 分區；flow 裡排在 latest 之後、爬取前）；-f/-t YYYYMMDD 區間、-o 輸出名
poetry run python -m twrhctl monthreport         # 月報 quality gate：疊 manifest 出月窗（0=綠、2=紅）
poetry run python -m twrhctl notify --text …     # Slack 通知（publish.sh 用）

# 離線／重放工具
poetry run python tools/quality_offline.py --date …    # 跑斷言引擎（sync 回 manifests/ 即可）
poetry run python tools/rerun_from_raws.py --from … --to … [--parquet-dir artifacts]  # 從 raw 日包重放 detail parser；給 --parquet-dir 產 parsed 分區檔（rerun-<ts>），否則 dry-run
poetry run python tools/compare_parsed.py A B                 # 兩組 parsed parquet 逐欄比：pipeline 分區 vs rerun 重放、或新舊 parser 版本 diff
./tools/sync-dev-data.sh                               # 成員用：拉 manifests/＋近 N 天 raw 日包＋list/、parsed/ 分區（需 bucket 讀權限）

# 雲上營運（AWS_PROFILE=twrh；三條 EventBridge 排程：日跑 02:10、前緣掃描 05/08/11/14/17/20/23、
# 月度出貨每月 1 日 07:00，皆 Asia/Taipei；定義在 devop/aws/*.tf）
poetry run python devop/runcheck.py [YYYY-MM-DD]        # 當日雲上驗收摘要：task／stage 時間軸／manifest／日包
./devop/aws/publish-cloud.sh [YYYYMM] [--dry-run|--resume --quality-issue <id>]   # 起一個 publisher task 跑 publish.sh
./devop/aws/run-cloud.sh <command...>                   # 用 crawler image 跑一次性指令（twrhctl 補跑、flow --from），runbook 見 devop/aws/README.md
# 臨時上雲測 list/detail 前先暫停掃描：cd devop/aws && terraform apply -var enable_sweep_schedule=false
# run-task 一次只發一個、發完 list-tasks 確認（09-04 誤發兩個搶同一 queue 的教訓）
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

`twrh-dataset` has a DB-free unittest suite — the file-queue semantics matrix (arch 2-3 B 層, ported from the
Django／PostGIS matrix in S6), fold／latest／seeding／manifest／assertion engine, and `twrhctl/tests`
(no command may import django):

```bash
cd twrh-dataset
poetry run python -m unittest discover -s tests -t .
poetry run python -m unittest discover -s twrhctl/tests -t .
```

spider 行為驗證仍是 manual，by running spiders against small real datasets（金門縣 list／deals、
detail `-a batch_size=15`，把 TWRH_ARTIFACT_DIR／TWRH_RAW_DIR 指到暫存目錄、不設 TWRH_RAW_BUCKET 就不會上傳）。

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
S6（2026-10）起沒有 DB：每個 stage 讀寫按日分區的檔案（EFS `/data`＋S3 bucket `twrh-w2`），
S3 是唯一真相來源（architecture-roadmap 的北極星，Phase 4 已結案 2026-09-26）。
1. `list591` spider walks 591 search pages per city, sorted by post date; the pipeline writes one
   list stub per house (`artifacts/list/…`) plus raw HTML to scratch, and one detail seed per listing
   goes into the file queue.
2. `detail591` spider crawls the seeded listings' detail pages → parsed rows (`artifacts/parsed/…`).
3. `deal591` spider (#229, deals stage) walks each city's 已成交 list (`list?shType=clinch`,
   newest deal first, 50/page with a 30-row page step so adjacent pages overlap by 20) down to
   `lookback_days` and emits one DEAL event per known house with 591's own deal date and
   「N天成交」 as `n_day_deal` (`artifacts/deals/…`). Since the 2026 redesign a dealt listing's detail
   page is a 404, so this is the **only** deal signal; houses never seen by list are counted, not created.
4. `CrawlerPipeline` (the only item pipeline) writes files only: raw HTML → `raws/scratch/`, normalized
   rows → `artifacts/scratch/` shards; `rawpack`／`artifactpack` turn them into day packs／partitions.
5. `snapshotfold` folds yesterday's snapshot + today's list／parsed／deals partitions into
   `snapshot/<vendor>/<date>.parquet` (one file a day; carry columns replace the old synthts／syncstateful);
   `latestfold` keeps the all-houses latest-state table `latest/<vendor>/daily/<date>.parquet`.
6. `manifest` writes `manifests/<date>/{list,detail,deals,snapshot}.json` from the partitions;
   `qualitycheck` asserts `quality/assertions.yaml` against them and posts the single Slack
   summary/alert (errors also go to Sentry).
7. `export -p` (1st of month) writes `[YYYYMM][CSV][Raw] TW-Rental-Data.zip` into `twrh-dataset/datas/`
   from the month's snapshot partitions.
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
`crawler/spiders/persist_queue.py` + `django/rental/filequeue.py` are the reason crawls are resumable
and why the pipeline is date-keyed:
- The queue is files: `artifacts/queue/<vendor>/<date>/<type>/{seeds/<run>.jsonl, terminals/<run>/<worker>.jsonl}`
  (type＝list／detail／deal). One seed line per work item (key＝`filequeue.make_key(seed)`; list keys carry
  the run so each sweep round re-seeds), append-only terminal lines per worker. Fold semantics: done＞dead＞
  failed, attempts = max across files; errback／parse error always write a terminal（failed 可重試、達
  `TWRH_QUEUE_MAX_ATTEMPTS`（3）轉 dead）。收工鐵律＝`twrhctl queuefinalize`：`done + dead == seeds` 且無殘留，
  紅→pipeline 中止。
- Claiming is a static positional shard over the day's full seed set (`filequeue.claimable`: primary 0,
  workers 1..N, count=N+1); after all workers stop the primary mops up with count=1 (also retries failed).
  At most `queue_length` (30) requests live in memory. `queuebusy` looks at worker heartbeat files.
- `detail591 -a batch_size=N` stops after N completions and touches the `stop_marker` file; flow's
  consume loop restarts the spider until it exits without touching it — this bounds memory over a
  multi-hour detail crawl. Overall progress survives restarts via
  `logs/progress/<YYYY-MM-DD>.detail.json` (`ProgressTracker.init_overall`).
- `--append` mode: list spider always regenerates seeds; detail spider only picks houses never
  detail-crawled.
- Detail seeding has three modes, all from files (`rental/known.py`＝總表 latest(昨日)＋今日 list stub；
  昨夜總表沒摺成就往回找最近一份、把之後每天的 stub 併進來）: `full`（全量 OPENED）、`diff`
  （`TWRH_DETAIL_SEED_MODE=diff`，production 現行，L-C list-diff skip 降頻：純函數
  `seeding.seeds_from_files` 讀今日 stub＋昨日 snapshot 的 carry 欄，stale/指紋變/連續≥2天缺席/
  回列才入 queue；材料不齊排全量；被 skip 的戶由 snapshot fold 以 carry 列延續）、`new`
  （只排今日在列、從未 detail 的 OPENED，前緣掃描用，不受同日 progress 檔防呆限制）。
  seed spider 把算 stale 用的 `now` 與四類計數留在 `logs/progress/<date>.seed.json`。
  stale 門檻自 2026-09-11 起 per-house 抖動 ±`TWRH_DETAIL_REFRESH_JITTER`（預設 2）天，
  house_id 雜湊決定（`rental/seeding.refresh_days_for`）——攤平
  9/2 bootstrap 全量在 7 天後同日到期的回波（9/10 detail 43,827 vs 平常 7,300）。
- **前緣掃描**（`flow.py sweep`，EventBridge 白天每 3 小時，避開 02:00–05:00 主跑）：
  `list591 -a frontier_pages=N` 逐頁走每縣市 list 最前面（排序鍵＝刊登時間，新刊登連續），
  整頁都是已知物件（`rental/known.py`）即收單；接 `detail591 -a seed_mode=new`＋`queuefinalize`。目的＝
  補抓刊登不到一天就成交的短命物件（一天一次 02:10 只看得到一半）。同一日期 bucket、同一張
  queue；被掃到的物件隔天早上因 detail 很新被 diff 判 skip。起跑先 `queuebusy`（同 vendor 同日
  bucket 2h 內有 worker 心跳即讓路 exit 0）；收尾 rawpack 把本輪 raw 併進當日日包。
  雲上（有 `TWRH_CLUSTER`）的 newdetail 與日跑 detail 同一套多 worker 模型：`seed_only` 先產本輪
  新種子 → 開 `sweep_workers`（profile 預設 2，env `TWRH_SWEEP_WORKERS`，0＝行程內兩趟）個
  consume-only worker（速率＝sweep 速率）→ primary 吃分片 0 → worker 全停後 primary count=1
  補掃（兼撿 failed 重試）；本輪沒新種子不開 worker。
- List pagination（package 端）不信 591 的 `total_page`：宣稱頁範圍當下限，前緣逐頁探測
  直到空結果頁收單；list manifest 的 `capture.ratio`（當日 OPENED 中出現在 list 的比率，
  assertions `list.capture.ratio` min 0.85）監控捕獲率。
- `--start-early`: when run at/after 22:00, bucket the data under tomorrow's date.

### S6：Django 退場（2026-09-26 平行比對起、10 月切換）
- `twrhctl/`（`poetry run python -m twrhctl <cmd>`）是 scrapy 以外的唯一指令入口；指令介面同舊 Django
  BaseCommand（`twrhctl/base.py`），行程內不得載入 django（`__main__` 斷言、`twrhctl/tests` 驗）。
  切換門檻：9/27 起每晚兩路（manage.py vs twrhctl）逐項比對 10 項、10/1 九月月包兩路逐 byte 一致（結果記在
  docs/architecture-roadmap.md 時間軸）。
- 爬蟲行程不起 Django；台北時區工具 `rental/tz.py`（Django timezone 的等價物）。
- `twrh-dataset/django/` 目錄名沿用（歷史佈局，裡面只剩純模組 `rental`／`crawlerrequest`），且有
  `__init__.py`——在 twrh-dataset 目錄下 `import django` 會拿到它；Sentry 的 auto_enabling_integrations 會試
  import django，所以 twrhctl 與爬蟲的 Sentry 初始化都關掉它。
- 歷史：DB 時代的 House／HouseTS／HouseEtc／RequestTS 最終版留在 S3 `archive/rds/`（S2b 的 RDS export）與
  RDS snapshot `twrh-final`（十月出貨確認後刪）；要讀舊 schema 看 git 歷史（`django/rental/models.py` 在 S6 前的版本）。

### TWRH_TARGET_DATE
`flow.py` exports `TWRH_TARGET_DATE=YYYY-MM-DD`（`--date`，預設今天）and pins it for the whole run so
a crawl that spans midnight doesn't split across two date buckets. It is read by `rental.tz`（`current_*`／
`target_datetime`）, `crawler/utils.now_tuple`, `persist_queue`, and the twrhctl commands.
Set it manually (or use `flow.py run --date`) when re-running part of a pipeline for a past day.
`export` honours it too (fixed 2026-08-28; it used to always take the real current date).

### Data contracts (twrh-dataset)
- Schema 單一定義在 `django/rental/contracts.py`（只增不改；取代舊 models.py）：list stub、parsed 列
  （GenericHouseItem 全欄＋`parser_version`；座標拆 `rough_lat`／`rough_lng`、author 只留雜湊、JSON 欄存字串）、
  deal event、snapshot（parsed 全欄＋carry 欄）、latest。
- Deal status is sticky: once a house is `DEAL`, a later `NOT_FOUND` does not overwrite it（fold 的成交段在
  `rental/deals.py`：deals 事件勝、inferred 語意、n_day_deal 推導）。
- 關閉／成交當天那列保留最後已知狀態（2026-09-12 拍板）：fold 對 404 關閉列（pipeline 寫的只帶 deal_status
  的 parsed 列，`contracts.is_closure`）只改狀態不清值。
- queue 的 request type 有三種：`LIST` / `DETAIL` / `DEAL`（`crawlerrequest/enums.py`）；queuefinalize's
  zero-seed rule applies to list/detail only (a day without a deals run is legal), residue rules to all.
- Raw HTML（arch 3-1／D5）：pipeline 落 `raws/scratch/`，收尾 `rawpack` 打成
  `raws/<vendor>/<date>.tar.zst`＋index 上 S3；**同日多次 run（日跑＋各輪 sweep）各自 rawpack，
  與既有日包聯集、後爬者勝**。修完 parser bug 後用 `tools/rerun_from_raws.py --parquet-dir` 對日包重放、
  **不需重爬**。
- **檔案分區**：pipeline 把 normalized 列寫到 `artifacts/scratch/`（每行程一個 jsonl shard），flow 的
  `liststubs`／`parsed`／`dealevents` stage 用 `artifactpack` 打成
  `artifacts/list/<vendor>/<date>/<run>.jsonl.zst`（list stub：一戶一輪一觀測，`fingerprint`＝sha1(price,title)）、
  `artifacts/parsed/<vendor>/<date>/<run>.parquet`、`artifacts/deals/<vendor>/<date>/<run>.parquet`，上同一 bucket
  的同名前綴。**一輪一檔（run／sweep-HHMM），永不改寫別輪**，與 rawpack 的同日聯集刻意不同。
  **`vendor_extra`＝整份 detail_dict 原樣落地**（parsed_version 2，2026-09-14 拍板）：parser 只維護站方今天的版式、
  raw 只留 365 天，parser 死掉的年代只剩它可讀；snapshot 跟著攜帶最新一次 detail 的；上線前的分區與 snapshot 用
  `tools/backfill_vendor_extra.py` 從 raw 日包回補，是「永不改寫別輪」的顯式例外。
  snapshot：一天一檔，日跑先把昨日重摺成 final（輸入已齊，seed 之前），再摺今日 provisional；前兩日都缺時往回找
  最近一份逐日重放（都沒有＝以空的前日冷啟）。manifest 的 fill_rate 樣本刻意取當日 parsed 分區（snapshot 的
  「None 不蓋值」會遮住 parser 靜默失效）。local 佈局預設與 `raws/` 同層（`TWRH_ARTIFACT_DIR`，AWS `/data/artifacts`）。
  deal591 的事件 item 帶 `vendor_house_url`，`contracts.DEAL_EVENT_ITEM_KEYS` 必須與 spider 實際 yield 的 key 一致
  （9/12 首夜漏這個 key、整晚事件沒落 shard）。

### Scrapy settings layering (twrh-dataset)
- `crawler/general_settings.py` — committed, shared. Adds `django/` (pure modules) to `sys.path`,
  loads `.env`, registers `CrawlerPipeline` and the Sentry extension, and sets the polite defaults: `ROBOTSTXT_OBEY=True`, `AUTOTHROTTLE_ENABLED=True`,
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
- `.github/workflows/dataset-tests.yml` runs the `twrh-dataset` unittest suites (`tests/`, `twrhctl/tests/`;
  no DB) on pushes/PRs touching `twrh-dataset/`.
