# 開放台灣民間租屋資料

長期收集各租屋網站、品牌公寓的可公開資訊，清洗後整理成格式統一的資料，供後續有需要的人使用。

- 專案資訊請見 [hackpad](https://g0v.hackpad.tw/Ih7Jp4pUD5y)。
- 爬蟲套件請見 [PyPI](https://pypi.org/project/scrapy-tw-rental-house/)

## 爬蟲本人

關於環境需求與使用方式，請見[套件網頁](https://pypi.org/project/scrapy-tw-rental-house/)。

## 資料 pipeline（twrh-dataset）

2026-10 起不用資料庫：每個 stage 讀寫按日分區的檔案（本機目錄或 EFS，並同步到 S3），
S3 上的分區就是唯一的資料來源。

### 環境需求

1. Python 3.10+
2. [Poetry](https://python-poetry.org/)
3. `zstd`（raw 日包與 list 分區的壓縮）

### 安裝與設定

```sh
poetry install

# 設定檔（皆 gitignored）
cp crawler/settings.sample.py crawler/settings.py
cp .env.example .env && vim .env   # proxy／UA／速率、Sentry、Slack、檔案位置
```

### 爬蟲使用方式

```sh
poetry run python flow.py run      # 日跑：list→liststubs→snapshotfinal→latest→seed→detail→deals→queuefinalize→rawpack→parsed→dealevents→snapshot→export(1 日)→manifest→quality→logs
poetry run python flow.py sweep    # 前緣掃描（白天每數小時）
poetry run python flow.py status
```

scrapy 以外的指令都走 `twrhctl`：

```sh
poetry run python -m twrhctl                 # 列出全部指令
poetry run python -m twrhctl export --help   # 資料匯出：-p 出上月月包，-f/-t YYYYMMDD 區間
```

### 監控與通知

專案支援透過 Slack Webhook 接收爬蟲執行統計通知。

#### 設定 Slack 通知

1. 在 Slack 中建立 Incoming Webhook：https://api.slack.com/messaging/webhooks
2. 在 `.env`（或環境變數）中設定 Webhook URL：

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

3. 執行 `qualitycheck` 指令時，系統會把當日品質斷言結果發送到 Slack（單一通道）：

```bash
poetry run python -m twrhctl manifest        # 先產出當日 manifests/<date>/<stage>.json
poetry run python -m twrhctl qualitycheck    # 對 manifest 跑 quality/assertions.yaml 的斷言
```

通知訊息包含：
- 當日摘要（總爬取數、已關閉／已成交／新增、list 完整度、成交事件）
- 失敗的斷言：`[stage] 斷言 id 觀測值 vs 門檻`（綠燈只有摘要）
- queue 收工對帳（`queuefinalize`）紅燈另有一則，並同步回報到 Sentry（如有設定）

#### 注意事項

1. 請友善對待租屋網站，依其個別網站使用規則容許的方式與頻率來查詢資料，建議可使用 Scrapy 內附的
   [DOWNLOAD_DELAY](https://doc.scrapy.org/en/latest/topics/settings.html#std:setting-DOWNLOAD_DELAY) 或 
   [AUTO_THROTTLING](https://doc.scrapy.org/en/latest/topics/autothrottle.html) 調整爬蟲速度。
2. 爬蟲以收集各網站可散佈的共同資料欄位為主，不會儲存所有網頁上的欄位。
3. 使用者使用本專案提供程式來進行公開資訊的分析與調取，其使用行為及後續資訊的利用行為，
   需符合現行法令的要求且自負其責，包括但不限於個人隱私、資料保護、資訊安全，以及公平競爭等相關規定。
4. 其他事項請參見[授權頁面](LICENSE)。

