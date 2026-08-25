# 開發體驗（DX）改善計畫

> 所有 `檔案:行號` 都經過實際查證；若之後檔案有大幅變動，請以行號附近的程式碼為準。
> 編修紀錄見文末。

這份文件回答三件事：**現在卡在哪、要做什麼、以及刻意不做什麼**。
每一項都標註了放在哪個 package（見〈架構原則〉），以及為什麼排在那個順序。

---

## 架構原則（決定每個項目該放哪裡）

本專案有兩個維度，所有改動都要先決定屬於哪一邊：

1. **`scrapy-tw-rental-house`（公開、可重複使用的 PyPI 套件）**
   負責 anti-anti-crawler 與 web page parser。目標是 developer 下載後**幾乎可以直接使用**。
   - 唯一的例外是 anti-anti-crawler 所需的注入 token（目前是某個 JS 變數）。
     它**不可以隨套件發布** —— 道德上不應公開，而且公開會加速其失效。
   - 推論出的硬性約束：**這個 package 的測試與診斷工具不可依賴 Django / PostgreSQL / PaddleOCR**。
     這既符合「下載即用」，也讓公開 CI 跑得起來。

2. **`twrh-dataset`（營運）**
   多 crawler 平行處理、persistent storage、統計、匯出、告警。

> 目前的程式碼**已經正確實作了 token 的分離**：`PlaywrightUtils.__init__` 是
> `settings.get('BROWSER_INIT_SCRIPT', '')`，沒值只發 warning，套件本身不含值。
> 機制在、值不在 —— 這正是該有的樣子。曾外洩進 repo 的 token（`settings.fast.py`，見痛點④）
> 已於 2026-08-20 確認失效，處理方式就是 0-2 刪檔、不動 history。

---

## 背景：四個痛點與查證結果

### ① 591 改版後不會停下來 —— 成立，而且內建熔斷被自己關掉了

全專案沒有任何 `CLOSESPIDER_*` 設定或 `CloseSpider` 呼叫。錯誤被逐層吞掉：

| 位置 | 行為 |
|---|---|
| `twrh-dataset/crawler/spiders/persist_queue.py:235` | `except Exception` → log + traceback，接著照常 `next_request()` |
| `scrapy_twrh/spiders/rental591/request_generator.py:63` | `error_handler` 只 log |
| `twrh-dataset/crawler/pipelines.py:101` | 裸 `except:` → log 完照樣 `return item` |
| `scrapy_twrh/spiders/rental_spider.py:52` | 未知 enum → 回 `UNKNOWN_ENUM (0xffff)`，只 log |

**關鍵**：補上 `CLOSESPIDER_ERRORCOUNT` 也沒用。Scrapy 的 CloseSpider extension 掛在
`signals.spider_error` 上（見 venv 內 `scrapy/extensions/closespider.py:50`），而該訊號只在
exception 逃出 callback 時才發 —— `parser_wrapper` 先自己吃掉了，Scrapy 永遠收不到。
**要熔斷就必須同時改錯誤處理**，否則等於裝了假的安全帶。

**失敗有兩種模式，其中一種完全靜默**（這比「錯幾千次」更危險）：

- **會被算到**：`detail_dict['price']`、`['misc']`、`['floor']` 等直接下標（`detail_mixin.py` 約 15 處）
  → 丟例外 → 整筆 house 掉、`RequestTS` 列留著 → `statscheck` 有數字。
- **不會被算到**：`if 'deposit' in detail_dict` 類守衛（`detail_mixin.py` 6 處、`list_mixin.py` 10 處）
  → 欄位**靜靜消失**，item 照樣寫進 DB，`statscheck` 一片綠。

所以最壞情況是：**一次都沒錯，但押金／樓層／坪數整批變空**，要等有人看資料才發現。

另外 `statscheck` 是 `go.sh` 的第 5 步，跑完整個 pipeline 才執行 —— 就算它報警，也已經晚了幾小時。

### ② 無法分步驟驗證 —— 成立，但 parser 這半邊比想像中近

parser 層其實已經是可測的純函數，只缺 harness：

- `get_detail_raw_attrs(response)` 只吃 `scrapy.http.Response`
- `gen_detail_shared_attrs(detail_dict)` 只吃 dict
- 本機 `scrapy-tw-rental-house/trial/detail-archive/` 有 **431 個 detail HTML**（2025-03-12 存的）

真正無法分離的是 anti-anti-crawler：Playwright flag、init script、page methods、proxy 全部寫死在
`request_generator.py:36-62` 的 `gen_detail_request_args`。沒有「只驗證我拿不拿得到一頁 200 且非
`about:blank`」的入口 —— 而該判斷式 `detail_mixin.py:52-53` 已經寫好了，只是埋在全量爬蟲裡。

### ③ 無法 nightly / smoke —— 成立

CI 只有 `ui-deploy.yml` 與 `ui-pull-request.yml`，都只碰 `ui/`。Python 端零 CI、零測試
（`django/*/tests.py` 是空 stub）。`go.sh` 是全量、單機、要 DB + proxy + Playwright + PaddleOCR。

### ④ env 綁定、working tree 永遠髒 —— 成立，且比預期糟

- `twrh-dataset/crawler/settings.py` 有 gitignore ✓ 做法正確
- 但 **`twrh-dataset/crawler/settings.fast.py` 是 tracked 的**，含 token（`:71`）與
  `localhost:8000` proxy（`:54, :68`）。而 `scrapy.cfg` 只指向 `crawler.settings`，
  **沒有任何程式載入 fast** → 一個沒人用、卻把本機設定 commit 進公開 repo 的死檔案。
- **`scrapy-twrh-example/crawler/settings.py` 是 tracked 的** → 每次調 proxy/concurrency 都讓
  working tree 變髒。
- 全專案沒有 env var / dotenv 機制：deps 沒 `python-dotenv`，settings 只讀 `TWRH_TARGET_DATE`。

---

## 背景補充（2026-08-20，來源：IvanaGyro 的 #204／#205 與本機實測）

1. **痛點①已實際發生**：591 改了 detail page 的 DOM class，`supported_facility` /
   `unsupported_facility` / `misc` / `promotion` 全空，且 `get_shared_boolean_info()` 對 `None`
   丟 `TypeError` —— 每一間房的 detail `GenericHouseItem` 都產不出來（#204）。
2. **不插隊搶修**：已壞一段時間、沒有新增損失的壓力，維持「先安全網（Phase 1）再動 parser」的順序。
   #204 的新舊 selector 對照表留作 2.5-1 的素材。
3. **591 detail 已回純 SSR**：純 HTTP 就含所有欄位（實測 118KB，render 完的 DOM 1315KB）。
   `wc-obfuscate-c-*` 元素已消失，OCR 路徑不會被走到（#205）→ 4-5 改為整組拔掉 OCR。
4. **431 檔是 2025-03 的舊 DOM**：只能當舊版式回歸 golden；現行 baseline 改用 1-2 的新鮮 harvest。
5. **`settings.fast.py` 的 token 已確認失效**（2026-08-20）：0-2 刪檔即可，不動 history、不必換 token。

### IvanaGyro 貢獻的採納清單（#204 / #205）

**credit 給法**：優先請作者把零件拆成小 PR（authorship 留在他的 commit）；若由我們自行改動，
commit 加 `Co-authored-by: Ivana <11438642+IvanaGyro@users.noreply.github.com>` 並引用 #204/#205。

**時序**：唯一的順序 gate 是「逗號修正 + UA 修正要在 2.5-1 開工前入 repo」（2.5-1 會大改同一批檔案，
之後 rebase 成本高）。其餘與 roadmap 全部平行，不等待；拆 PR 設時間窗，逾期自作 + Co-authored-by。
他的測試套件是 1-3 的參考而非直接 merge——其中 fallback middleware 的測試不採納，
fixture 也要改按 1-4 的策略重做。

| 項目 | 去處 |
|---|---|
| `SimpleNuxtInitParser` 逗號切分 bug 修正 | 直接收；實例 21788398 的 `rgb(20, 106, 153)` 就會觸發 |
| `USER_AGENT`：591 對 Scrapy 預設 UA 回 403 的修正 | 直接收 |
| pytest 離線測試骨架：fixture HTML、conftest **擋 socket**、fixture 假個資 | 1-3 的起點 |
| `detail_591_not_found.html` fixture | 分層維度「已下架／已成交頁」 |
| `'已辦理' in (x or '')` 類 None guard | 採納，須與 2-2 填充率告警同時上（單獨上會把 crash 換成靜默消空） |

知識與素材（non-code，同樣註明出處）：

- #204 的新舊 selector 對照表、`deep_text`/`self_text` 差異、tooltip 汙染、
  「產權登記」字串已變為「房屋已辦產權登記」→ 2.5-1 的素材。
- `PersistQueue` 的單一 response 約束 → 踩雷筆記。
- AI triage 提議 → 另案處理（見〈建議不做〉）。

不採納：`PlaywrightFallbackMiddleware` 本體與整包合併（理由見〈建議不做〉）；
PaddleOCR lazy-load（OCR 將整組拔掉，見 4-5）。

---

## Roadmap

排序依據是**依賴關係 → 解除阻塞的程度 → 風險**，不是依痛感。
Phase 0 有兩項看起來不重要，但它們是**乘數**：working tree 髒、以及改 core 要先 publish 才能驗，
會讓後面每一項的成本都變高。先付掉。

成本標示：極小（< 1h）／小（半天內）／中（1–2 天）／大（3 天以上）。

### Phase 0 — 解除阻塞

| # | 項目 | 位置 | 成本 | 理由 |
|---|---|---|---|---|
| 0-1 | 設定改 env var + `python-dotenv` + `.env.example`；example 的 `settings.py` 改成 `settings.sample.py` 並 gitignore 實檔 | 兩邊 | 小 | working tree 從此乾淨，之後每個 PR 的 diff 才可讀 |
| 0-2 | 刪 `twrh-dataset/crawler/settings.fast.py` | dataset | 極小 | 死檔案，且把 token 與本機 proxy commit 進公開 repo。token 已確認失效，刪 HEAD 即可 |
| 0-3 | 開發時 core 改用 path dep / editable install | dataset | 小 | 現在改 parser 要先 `poetry publish` 才能在真 pipeline 驗 |
| 0-4 | 清死碼：`twrh-dataset/crawler/middlewares.py`（未註冊的 103 行 scrapy 樣板）、`scrapy-tw-rental-house/trial/setup.py`（setuptools 1.2.0，與 Poetry 並存） | 兩邊 | 極小 | 純降低閱讀成本 |

**產出**：`git status` 乾淨、改 core 不必發版。

### Phase 1 — 離線安全網（一切改動的前提）

沒有這層不敢動 parser。**不需要 token、不需要 DB、不需要連網**（1-2 除外）。

| # | 項目 | 位置 | 成本 | 說明 |
|---|---|---|---|---|
| 1-1 | fixture git 策略（已拍板 2026-08-20）：**值全換的最小集進 git** | — | 決策 | 個資與著作權內容（標題、屋況介紹）都不進 git；scrub 標準見 1-4 |
| 1-2 | `twrh-harvest`：分層取樣器（1-5 與 2.5-2 都依賴它） | package | 中 | list 頁已帶 `property_type`(`list_mixin.py:211`) 與 `contact_info`(`:261`)，取樣很便宜 |
| 1-3 | golden snapshot 測試：`HtmlResponse` → `get_detail_raw_attrs` → 比對 committed JSON | package | 小 | parser 已是純函數，只差 harness。起點：#205 的 pytest 骨架（含擋 socket 的 conftest） |
| 1-4 | scrub 器 + **「scrub 前後 parse 結果必須相同」** 的自我驗證斷言 | package | 中 | 標準：白名單容器 + **所有文字值換合成值**（個資與著作權一併解）。見〈踩雷筆記〉的 `<script>` 與 scrub 實例查證 |
| 1-5 | 欄位填充率 baseline，用 1-2 的新鮮 harvest 計算 | package | 小 | 431 檔是舊 DOM，只當 2025-03 版式的回歸素材 |

**分層維度必須由程式碼實際的分支決定，不是憑感覺**：

| 維度 | 漏了就測不到什麼 | 證據 |
|---|---|---|
| `property_type`：車位 / 整層住家 / 其他（套房·雅房） | 三類用**不同的 `item_list` 位置**解析 | `detail_raw_parser.py:90-102`；`list_mixin.py:353` 對車位 early return |
| contact：屋主 / 仲介 / 代理人 | 依字串前綴分支 | `list_mixin.py:418-420` |
| 價格區間（社會住宅） | `min_monthly_price` 分支（#87） | `rental591/util.py:29` |
| floor 字串：`1F/2F` / `頂樓加蓋` / `B1` / `整棟` / `1F~3F` | 五種格式各自分支 | `list_mixin.py:365-380` |
| 已下架 / 已成交頁 | `.error-info` 與非 200 兩條路 | `detail_mixin.py:52, :78` |

### Phase 2 — 止血

| # | 項目 | 位置 | 成本 | 說明 |
|---|---|---|---|---|
| 2-1 | 錯誤率熔斷 extension（滑動視窗：樣本 > N 且失敗率 > X% → `close_spider`） | package（機制）+ dataset（門檻） | 中 | **必須同時改 `parser_wrapper`**，否則熔斷收不到訊號 |
| 2-2 | 欄位填充率收集 extension → 與 1-5 baseline 比對 | package（收集）+ dataset（比對告警） | 中 | 唯一能抓到「不報錯但欄位整批消空」的手段 |
| 2-3 | `statscheck` 加比例門檻 | dataset | 小 | 現在任何一筆失敗就發 ⚠️（`statscheck.py:182`），告警疲勞 |

### Phase 2.5 — 純 HTTP 優先與大規模量測（採 #205 的動機，不採其做法）

591 detail 已回純 SSR。fallback／迴避機制的形狀由量測結果決定，不預先選定 playwright。
順序：純 HTTP parser → 大規模驗證 → 設計 fallback。

| # | 項目 | 位置 | 成本 | 說明 |
|---|---|---|---|---|
| 2.5-1 | detail parser 直接吃純 HTTP response；selector 依 #204 對照表修正（注意 `deep_text`、tooltip 汙染、「房屋已辦產權登記」字串變更） | package | 中 | 需要 Phase 1 安全網先就位 |
| 2.5-2 | 大規模量測：純 HTTP 的成功率、被擋的形式（403／驗證頁／空頁）、觸發條件（速率？總量？IP？） | dataset | 中 | 與 1-2 harvester、L2 probe 共用同一支程式 |
| 2.5-3 | 依量測結果設計 fallback／迴避機制 | 兩邊 | 待量測後估 | 也許換 UA、降速就夠；playwright 只是選項之一。**重試要放 downloader middleware**，見踩雷筆記關於 PersistQueue |
| 2.5-4 | `twrh` CLI：手動測試入口（Poetry console script） | package | 小 | 子指令：`parse`（離線吃 HTML 檔跑 parser）、`list <縣市名或 list URL>`（抓一頁 list、輸出解析結果與欄位命中率）、`detail <house-id 或 URL>`（抓單一 detail、輸出 parse 結果）、`survey <縣市名或 list URL>`（全量 list + 全部 detail，**不寫 DB**，輸出完整性報告：list/detail 成功率、`property_type` 分布、每欄位填充率與 baseline 差異；`--save-html` 存 fixture 候選）。縣市 → URL 用 `tw_regions.json` 對應，也接受直接貼 URL。與 1-2 harvester、3-1 doctor 共用 plumbing，後兩者做完即併為同一支 CLI 的子指令；`survey` 就是 L3 drift detector 的手動介面（見 3-3） |

### Phase 3 — 線上診斷與 nightly

| # | 項目 | 位置 | 成本 | 說明 |
|---|---|---|---|---|
| 3-1 | ~~`doctor` / `probe` 分階段診斷~~ **已併入 3-2**（2026-08-25） | package | — | 原四項檢查中：(a) proxy 與 token 檢查隨 2.5-1 拔除 playwright／`BROWSER_INIT_SCRIPT` 而失去對象；(b) 被擋形式偵測等 ramp-up 有真實樣本再加（同 2.5-3 的暫緩理由）；(c)(d) 併入 `twrh probe` 的哨兵斷言。獨立 doctor 不再需要 |
| 3-2 | 三層 nightly；入口 `twrh probe` = survey plumbing + 比率斷言 + exit code | 兩邊 | 小 | 見下。probe 供 cron 以 exit code 判紅綠 |
| 3-3 | drift detector 與 harvester 共用同一支程式 | package | 小 | 差別只在要不要寫入 baseline；手動介面即 2.5-4 的 `twrh survey`，baseline 比對掛在 `twrh probe --baseline` |

**三層設計（這是「591 資料每天變、ID 不會永遠有效」的解法）**：

- **L1 離線 golden**（每個 PR，公開 CI）：凍結 HTML、不連網，ID 永久有效。
  回答「我的改動有沒有弄壞 parser」。
- **L2 live probe**（nightly，自架 runner）：**不 hardcode 任何 ID**。抓 list（花蓮縣——物件量小
  但類型較多元，比金門縣更能踩到各 property_type 的分支）→ 取**當下**前 K 筆 → 抓 detail。
  斷言全部是比率／不變量：
  - list 至少回 N 筆
  - detail ≥X% 得到 200 且 raw parse 成功（404 是預期行為，斷言下在比率）
  - 其中 ≥X% 解出 price / floor / floor_ping（selector 漂移哨兵）
  - 舊版式（`LEGACY_MARKERS`）出現率哨兵，**雙向**告警（2026-08 已歸零；若再出現代表 591 版式回退或恢復圖片混淆）
- **L3 drift detector**（nightly）：harvest 新鮮分層樣本 → parse → 比對填充率分佈與 baseline。
  抓的是「591 變了」，不是「我的 code 變了」，同樣不需要穩定 ID。

**核心規則：對「當下新發現的 ID 的比率」下斷言，永不對特定 ID 或特定值下斷言。**
個別 404 是**預期行為**（`request_generator.py` 註解：591 用 30x 表示房源狀態，故 `dont_filter=True`），
所以樣本小、斷言用比率、失敗給一次重試。

**閉環**：L3 一響，它剛抓下來的 HTML 就是下一版 fixture 候選 → harvester 與 nightly 是同一支工具。
這也回答「golden fixture 會不會過期」：golden 集**刻意永不變**（那正是回歸測試的價值），
世界變了交給 L3。manifest 記錄抓取日期，每季再補一組新的、舊的留著。

**nightly 不可寫正式 DB**（會污染 `HouseTS` 與 `n_day_deal`）—— 跑在 package 側、feed export 出 JSON、
不掛 `CrawlerPipeline`，剛好也符合〈架構原則〉的分界。

### Phase 4 — 結構性（不急，但為新站點鋪路）

| # | 項目 | 位置 | 成本 | 說明 |
|---|---|---|---|---|
| 4-1 | `enums.py` 與 `tw_regions.json` 單一來源（django 端 import package） | 兩邊 | 中 | 現在兩份且**已漂移**，見〈踩雷筆記〉 |
| 4-2 | `go.sh` 改用 exit code / DB 狀態取代 `grep -q 'Batch limit reached'` | dataset | 小 | 用 log 字串當控制流，改一句訊息就壞 |
| 4-3 | `RequestTS.seed` 改成有 key 的 dict | dataset | 中 | 現在 `ListRequestMeta(*seed)` 是位置參數，改欄位順序會靜默錯位。需要 migration |
| 4-4 | `PersistQueue.queue_length` / `n_live_spider` 從 class attribute 改 instance | dataset | 極小 | 現況靠 `self.x -= 1` 隱式建實例屬性，是 footgun |
| 4-5 | **拔掉 OCR**：移除 paddlepaddle/PaddleOCR 依賴、`ocr_utils.py`、`parse_obfuscate_fields`、`OCR_CACHE_*` 設定 | package | 小 | **已併入 2.5-1 一次做掉**（2026-08-25，見編修紀錄——不留舊版式 parser，OCR 失去唯一的存在理由）。若 591 恢復圖片混淆（L2 哨兵會告警）再重新引入 |
| 4-6 | 多站點抽象：`PersistQueue` 的 vendor 改從 spider class attribute 取；enums 拆 shared vs vendor-specific | 兩邊 | 大 | **由真的要加第二站時驅動**，見〈建議不做〉 |

### Backlog（已知但痛感低）

- `PersistQueue.next_request()` 的認領不是 atomic（`persist_queue.py` 註解自承 #21），
  靠事後 `deduprequest` 兜底。Postgres 可改 `SELECT ... FOR UPDATE SKIP LOCKED`。
- `parser_wrapper` 結尾的 `mercy = 10` 迴圈（`persist_queue.py:256-264`）是沒有說明的魔術數字。
- `export` 指令**不讀** `TWRH_TARGET_DATE`，永遠用真實當下日期 —— 用 `go.sh --date` 重跑舊日期時，
  匯出的檔名／範圍會對不上。
- `ui` 的 Node 版本不一致：`.nvmrc` 是 16，CI matrix 是 14。

---

## 建議不做

| 項目 | 理由 |
|---|---|
| **把 431 個 HTML 整批 commit** | 37MB，且含電話／詳細地址／照片 URL，直接違反 README 注意事項 2、3（只收集可散佈的共同欄位）。改為 manifest + snapshot 進 git、raw HTML 不進、另備 15–25 檔 scrub 過的最小集給 CI |
| **rewrite git history 抹掉 token** | 會打斷所有 g0v fork / clone，且 token 已確認失效（2026-08-20），收益為零。刪 HEAD 即可 |
| **只設 `CLOSESPIDER_ERRORCOUNT` 就當熔斷做完** | 已查證無效（見痛點 ①）。不改錯誤處理就設它，等於裝了假的安全帶 |
| **live smoke 放進公開 GitHub Actions** | 要把 token 放進 secret，且讓公開 repo 的 CI 去打 591。道德與實務都不好，改自架 runner 或本機 `make nightly` |
| **現在就做 4-6 多站點重構** | 沒有第二個站點時的抽象是猜的。`vendors.json` 裡 好房網／蟹居網 放了很久沒實作，說明需求沒那麼急。等真的要加時，用它驅動重構 |
| **補 Django 層的測試覆蓋率** | 真正的風險在 parser 與 anti-anti-crawler，不在 ORM。低報酬 |
| **升級 `ui` 的 Node / Nuxt 2** | Nuxt 2 已 EOL 是真問題，但與這四個痛點無關。不要混進這一輪。已另立獨立計畫 `docs/ui-roadmap.md`（2026-08-25，Astro 改版），與本計畫無相依、分開排程 |
| **刪 `scrapy_tw_rental_house` symlink** | 它是 Poetry 打包（套件名推導）與舊 import path 的必要條件 |
| **nightly 對特定 house ID 斷言** | 就是「ID 不會永遠有效」這個陷阱本身 |
| **整包合併 PR #205 的 `PlaywrightFallbackMiddleware`** | fallback 的形狀應由 2.5-2 的量測結果驅動，先上重型 fallback 是用方案蓋住還沒回答的問題。PR 的其他零件照〈採納清單〉收 |
| **這一輪就做 AI triage（nightly 壞了讓 AI 定位、修 selector）** | 方向好（IvanaGyro 於 #205 討論串提議），但依賴 L2/L3 先存在，且涉及流程與授權設計，另案處理 |

---

## 踩雷筆記（容易重複踩到的事實）

**關於 fixture 素材**
- `scrapy-tw-rental-house/.gitignore` 最後一行是 `trial`，所以**整個 `trial/` 不在 git 裡**。
  那 431 個 fixture 只存在於開發機。`trial/` 共 168MB、`detail-archive/` 37MB。
- `trial/examples/*.json` 是 **#176 之前的舊 591 API response**，不是現在 parser 的預期輸出。
  **不要拿來當 golden**。
- scrub fixture 時**不能無腦刪 `<script>`** —— `SimpleNuxtInitParser` 要解 Nuxt init script 才拿得到值。
  scrub 規則必須白名單化（保留 parser 實際 query 的容器 + nuxt script）。
- 431 檔是 2025-03 的舊 DOM（591 已於 2026 改版，#204）—— 只能當舊版式回歸 golden，
  不能當現行 baseline。現行 fixture 一律由 1-2 harvester 新鮮取得。

**scrub 實例查證（房屋 21788398，2026-08-20 抓取）**
- 標題是**同一字串重複 10 次**（`<h1>`、`<title>`、meta×3、JSON-LD×5、nuxt args），
  parser 只讀 `.title h1`（`detail_raw_parser.py:61`）→ 建 `{原文→合成標題}` 對照表全域替換即可，
  白名單化後其中 8 份根本不會留下。
- 屋況介紹有 **2 份**：DOM rich text（parser 讀這份，`.house-condition-content .article` 的
  `deep_text`）+ nuxt init script 裡的 `<` 逸出副本（parser 不讀）。
- **nuxt script 裡的副本要原地替換、不可刪除** —— 刪了會讓參數列表的逗號位置錯位，
  經緯度（parser 從 nuxt 讀的唯一資料）會對到錯的值。
- 合成文字要保留原文的「形狀」：emoji、全形標點、`<br>`、文字節點數量照舊。
  `deep_text` 是文字節點串接，節點結構變了「scrub 前後 parse 相同」的斷言會誤報。
- 屋況介紹 inline style 含 ASCII 逗號（`rgb(20, 106, 153)`），會觸發 `SimpleNuxtInitParser`
  的逗號切分 bug（#205 已修，見採納清單）。
- 著作權暴露面只有 fixture：`House` model 沒有 title/description 欄位，兩者只進
  `HouseEtc.detail_dict`，從不出現在發布資料集。

**關於 PersistQueue**
- 它假設**一個 queued request 只有一個 response**：parser 正常結束才 `db_request.delete()`。
  所以重試／fallback 不能寫在 `parse_detail` 裡，要放 downloader middleware、
  對 spider 透明地重送（#205，credit IvanaGyro）。

**關於 parser**
- OCR 是**欄位去混淆**（非 CAPTCHA 破解），將於 4-5 整組拔掉。拔掉前注意
  `get_detail_raw_attrs`（`detail_raw_parser.py:42-50`）的展開順序是刻意的：
  `parse_obfuscate_fields` 在前、`get_house_price` 在後，DOM 純文字覆蓋 OCR 結果。

**關於重複定義**
- `scrapy_twrh/spiders/enums.py` 與 `twrh-dataset/django/rental/enums.py` 是兩份複製，
  只差一行檔案路徑。
- 兩份 `tw_regions.json` md5 已不同：「新竹縣峨嵋鄉」與「新竹縣峨眉鄉」（同為 1304）順序相反，
  導致兩邊 `SubRegionType` 的正規名稱不一致。**這證明複製已經開始漂移**。
- enum 的整數值會出現在已發布的資料集裡 —— 只能新增，不能重新編號。

**關於既有工具**
- `twrh-dataset/tools/rerun_detail_raw.py` / `rerun_detail_dict.py` 可以用 `HouseEtc` 存的原始 HTML
  重跑 parser，**但需要連正式 DB**，所以它不能取代離線 fixture 測試。
- `twrh-dataset/crawler/settings.sample.py` 才是給人複製的範本；`settings.fast.py` 沒人用（見 0-2）。

---

## 編修紀錄

- **2026-07-30** 建立。對 `master`（`3d1bf69`）的程式碼盤點：四痛點查證、Phase 0–4、建議不做、踩雷筆記。
- **2026-08-20** 納入 IvanaGyro 的 #204／#205：新增〈背景補充〉與〈採納清單〉；新增 Phase 2.5
  （純 HTTP 優先 + 大規模量測，取代 playwright-as-fallback）；拍板 fixture 策略（值全換的最小集進 git，
  可行性以實例 21788398 查證）；1-5 baseline 改用新鮮 harvest（431 檔降為舊版式素材）；
  4-5 由「OCR 拆 Poetry extra」改為「整組拔掉 OCR」；AI triage 列為另案。
  同日補充：`settings.fast.py` 的 token 確認失效（刪〈需要拍板的決定〉，結論收進 0-2 與架構原則）；
  新增 2.5-4 `twrh` CLI 手動測試入口（parse／list／detail／survey 子指令，doctor、harvester 後續併入；
  `survey` 為單一縣市全量完整性報告，即 L3 的手動介面）。
- **2026-08-20 實作進度**（branch `feat/dx-groundwork`）：
  - **Phase 0 完成**（0-1 env var 流程、0-2/0-4 刪死檔、0-3 `dev-core.sh`）。
  - **2.5-4 `twrh` CLI 完成**（parse／list／detail／survey），以金門縣實測通過。
  - **1-5 第一份 baseline**：金門縣 27 筆——純 HTTP 全 200、raw 核心欄位 100%、
    `misc`/`facility`/`rough_coordinate` 0%、GenericHouseItem 0/27（#204 TypeError），
    報告在 `scrapy-tw-rental-house/survey-output/`（gitignored）。
  - **Phase 2 完成**（2-1 熔斷 + 自訂訊號、2-2 填充率監控、2-3 statscheck 比例門檻）。
    熔斷與填充率先放 dataset 側 `crawler/extensions/`——dataset 裝的是已發布 package，
    放 package 側會依賴未發布版本；2.5-1 發版時上移。已以 stub crawler 單元驗證，
    live 驗證待下次真實爬蟲。
- **2026-08-25 IvanaGyro 第二批 PR 的處置**：
  - **#208（nuxt 逗號切分）、#209（591 對 scrapy 預設 UA 回 403）已合併**——採納清單前兩項完成，
    2.5-1 的時序 gate 解除。pytest 骨架（`scrapy-tw-rental-house/tests/`、擋 socket 的 conftest）
    隨之入 repo，1-3 有了起點。
  - **#210（純 HTTP + parser 依版式分檔）已關閉，改由自己實作**，採納其：純 HTTP 化與移除
    playwright、#204 selector 修正、靜默錯值修正（`頂樓加蓋`→`頂層加蓋`、`車位費`→`車位租金`、
    `已辦理`→`房屋已辦產權登記`、無編號`陽台`）、離線測試與 fixture 方法論（白名單剪枝斷言
    parse 不變、scrub 斷言只改值）。commit 需 `Co-authored-by` 並引用 #210。
  - **拍板：不保留舊版式 parser**（否決 #210 的 dated-module dispatch 設計）。理由：重放路徑走
    `detail_dict`（`rerun_detail_dict.py`），不經 raw HTML；凍結 parser 只能重現已落庫的 dict，
    修 bug 或抽新欄位都得寫新 code，舊 parser 從 git history 或 PyPI 舊版號取得即可；
    dated module 是只增不減的 ratchet；且它是 PaddleOCR 活著的唯一理由。
    **4-5（拔 OCR/paddle）併入 2.5-1 一次做掉**。唯一保留的安全裝置：偵測到舊版式頁面
    → warn + skip，避免 rerun 工具對改版前 HTML 靜默 parse 出空欄位。
  - **L2 live probe 改用花蓮縣**（原金門縣）：物件類型較多元，較能踩到各 property_type 分支。
    金門縣仍適合當 CLI 快速 spot-check 的最小樣本。
  - #210 揪出的遺留問題，已本機確認：`scrapy-twrh-example/crawler/settings.py` 0-1 時只加了
    gitignore、沒 `git rm --cached`，仍 tracked 且含 `BROWSER_INIT_SCRIPT` token → 待 untrack
    並確認該 token 失效。
  - 連帶待辦：自實作落地後關 #205；#211（dependabot 清倉）的 poetry.lock 需在新 parser 定案後
    rebase（其 opencv/paddle 修補將隨 OCR 拔除而無對象），ui 那半可先拆出來收。
- **2026-08-25 實作進度**（branch `feat/pure-http-parser`，每項一 commit）：
  - **2.5-1 完成**：純 HTTP 化（拔 playwright 與全部 `BROWSER_*`）+ detail parser 重寫為
    **單一模組**（採 #210 的 selector 與 detail_mixin 修正；`misc_of` 讓 dict 層新舊 label
    都認，raw 層舊版式以 `LEGACY_MARKERS` 偵測、丟 `LegacyTemplateError` 拒絕）。
    #204 修復；金門縣 live 實測 detail_dict 與 GenericHouseItem 全欄位產出。
  - **4-5 完成**：OCR 整組拔掉（ocr_utils、paddle 依賴、OCR_CACHE 設定、README 段落）。
  - **1-3／1-4 完成**：115 個離線測試（擋 socket）、8 個剪枝+scrub fixture 入 git，
    dispatch 測試改寫為 legacy 拒絕測試。
  - **1-2 完成**：`twrh harvest` 分層取樣器——分層 = parser 實際分支（property／contact／
    價格區間／floor 五格式），稀有 bucket 先選，0 樣本 bucket 顯性回報；輸出 fixture 候選
    HTML + manifest（含填充率，即 1-5 baseline 的輸入）。花蓮縣實測：379 筆、11/12 bucket
    有樣本（車位、B1、頂加、代理人都有——金門縣掃不到這些），選 10 筆全數 parse 成功。
  - 註：1-5 花蓮縣 baseline 已可由本次 manifest 起算；正式 baseline 建議發版後以
    `twrh harvest` 定期重跑。CLAUDE.md 同步更新（無 playwright／OCR、單一 parser 政策）。
- **2026-08-25 盤點與決策（2.2.0 發版後）**：
  - **Phase 2 完成 live 驗證**：熔斷與填充率 extension（已於 2.2.0 上移 package 側）在真實
    單城市與大城市全量 crawl 中運作正常。
  - **2.5-2 首輪量測完成**：單一大城市全量純 HTTP 驗證通過；量測數據與門檻屬營運敏感資訊，
    記錄於非公開報告，不進本文件。**2.5-3 拍板暫緩**——首輪未觀察到任何被擋形式，
    fallback 沒有素材可定形狀；改為逐日加城市 ramp-up，取得真實觸發樣本後再設計。
  - **3-1 併入 3-2**（表格已改）：proxy／token 檢查隨 playwright 拔除而失去對象，
    剩餘價值收斂為 `twrh probe` 的比率斷言與 legacy 版式哨兵。
  - 遺留清理確認：`scrapy-twrh-example/crawler/settings.py` 已 untrack（repo 已無
    `BROWSER_INIT_SCRIPT`）；#205 已關閉。#211 的 poetry.lock rebase 條件已成熟（parser
    定案且 OCR 已拔），待處理。
  - 量測過程發現四個小問題，於同 branch 修復（見下一條）：
    (1) `PersistQueue.has_record()` 不分城市——同日先爬過任一城市後，其他城市的 list
    在一般模式會直接不生種子；(2) `FillRateMonitor` 同日多次執行互相覆蓋報告，
    批次迴圈下只剩最後一批；(3) `detail591 -a append=True` 的 `monthly_price__isnull`
    過濾失效——2026 改版後 list 頁 item 就帶價格，append 模式會跳過所有新物件；
    (4) detail progress 的 Overall 分母跨 restart 不隨新種子更新（純顯示問題）。
- **2026-08-25 實作進度（1-5 + Phase 3 + 四個小問題，每項一 commit）**：
  - 四個小問題全數修復：(1) list 種子生成改逐城市判斷（`has_record(top_region=…)`）；
    (2) `FillRateMonitor` 同日報告改累加；(3) detail append 過濾改
    `etc__detail_raw__isnull`（「從未爬過 detail」的本意）；(4) overall 分母改
    `max(stored, completed + pending)`。
  - **1-5 完成**：花蓮縣全量 survey（375/375 raw 與 generic 全數解析成功）產出正式
    baseline，committed 於 `scrapy-tw-rental-house/baselines/hualien-fill-rate.json`；
    parser 改版後以 `twrh survey 花蓮縣` 重新產出。
  - **3-2 完成**：
    - **L1 公開 CI**：`.github/workflows/python-tests.yml`——repo 第一個 Python CI，
      只跑離線 pytest（conftest 擋 socket），live 不進公開 CI。
    - **L2/L3 入口 `twrh probe`**：比率斷言（list 筆數、detail 200 率、raw parse 率、
      舊版式哨兵、price/floor/floor_ping 填充哨兵）+ `--baseline` 填充率漂移比對
      （即 3-3 的 drift detector，與 survey 共用 plumbing）+ exit code。
      離線斷言測試 9 個；花蓮縣 live 實測含 baseline 比對全數 PASS。
    - **`scrapy-tw-rental-house/nightly.sh`**：pytest + probe（含 baseline）。
      拍板：本機**不排 cron、維持偶爾手動跑**，轉正式環境後再掛真的 nightly。
  - Phase 3 至此收完；剩餘開放項：ramp-up 持續量測（2.5-2 延伸）、2.5-3（待真實
    被擋樣本）、Phase 4 的 4-1〜4-4、#211 poetry.lock rebase、Backlog。
