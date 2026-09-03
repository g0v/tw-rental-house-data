# 架構演進計畫（好維護・橫向擴展・模組可抽換）

> **狀態**：本文件由 Claude 起草（2026-09-03），**尚未經維護者完整 review**，
> 內容可能隨時變動；歡迎以 issue / PR 回饋。
>
> 目標：回答「如果為了**好維護、方便橫向擴展、可抽換模組**重新設計，這個專案
> 該怎麼調整」，並為**支援多租屋平台、讓更多人參與開發與測試**鋪路。
> 設計結論源自 2026-08 接手以來的事故與收斂經驗；依本專案慣例，
> 量測數據一律省略，只保留結構性結論。
>
> 本文也是 dx-roadmap 2.5-3 所指「queue 顯式終結狀態＋seeds==terminals」
> 設計的 repo 內正式落點。

---

## 一、核心診斷：三個目標對應同一組結構缺陷

八月以來的每一次事故——seed bug 零產出、robots 假性完成、403 靜默陣亡、
spider「正常 finished」但少一批資料——沒有一件是「爬蟲壞了」，全部指向兩個
根源：

1. **可變狀態**：House 原地覆寫、raw HTML 塞 DB、queue「刪列＝完成」。
2. **隱性控制流**：errback 靜默斷餵、log 字串當契約、四套編排機制
   （go.sh／orchestrate.sh／batch marker／progress 檔）拼一條 pipeline。

三個目標其實是同一件事的三面：

| 目標 | 結構性解法 |
|---|---|
| **好維護** | 把「可觀測」做進資料模型：終結狀態顯式、每階段附 manifest、告警單一通道——不是事後架檢查 |
| **橫向擴展** | 唯一的可變狀態收斂在一張 queue 表（顯式狀態機），其他階段都是「讀檔→寫檔」的純函數——worker 數、vendor 數、執行環境（本機／雲上）都變成水平參數 |
| **抽換模組** | 邊界用**資料契約**定義而非繼承：vendor 是「四個函數＋fixtures」、儲存是「按日分區的不可變檔案」、分析引擎是拋棄式（檔案是真相，引擎隨時換） |

---

## 二、目標形狀（北極星，不是第一步）

每個階段產出**不可變、按日期分區的檔案 artifact**，S3 為真相來源，
DB 降級為 queue 與索引：

```
 stage        產出（不可變、按日分區）              對應現制
──────────────────────────────────────────────────────────────
 list      →  list/<vendor>/<date>.jsonl.zst      list_dict（散在 HouseEtc）
 detail    →  raw/<vendor>/<date>.tar.zst＋index  HouseEtc.detail_raw（塞 DB）
 parse     →  parsed/<vendor>/<date>.parquet      HouseEtc.detail_dict
 snapshot  →  snapshot/<date>.parquet             HouseTS
 deals     →  deals/<date>.parquet                syncstateful 推導
 export    →  publish/<year>/[YYYYMM]….zip        export -p（不變）
```

三條規則貫穿全部：

1. **檔案存在＝該 stage 完成**——resumability、冪等、進度追蹤免費得到。
2. **只有 crawl 需要可變狀態**，收在一張 queue 表；其他 stage 都是純函數。
3. **每個 stage 附一份 manifest**，品質門檻＝對 manifest 的斷言。

這個形狀的紅利是連鎖的：re-parse 歷史＝重跑一個 stage（rerun 工具消失）、
歸檔與遷移＝檔案本來的樣子（rawoffload／archivehistory／housekeep／
DB 大遷移整條線消失）、合成快照（synthts）變成 snapshot stage 的定義本身
（沒爬的沿用昨日值＋標 `source=carry`）、開發環境零雲相依（sync 幾天分區
即可跑全 pipeline）。

**但它是方向、不是排程。** 專案這一個月其實已經用實作收斂到這個形狀的邊緣
（raw tar.zst 上 S3、公開 zip 當 TS 永久副本、distcheck history jsonl、
L-C list-diff）——接下來是**逐項偷回來，每一步獨立有收益**，不做 big-bang。

**與分階段的對應**（避免誤讀為「做完就是北極星」）：Phase 1–3 到達的是
北極星的**殼**——manifest／斷言機制、queue 顯式狀態機、raw 檔案化、單一
flow 定義；定義性特徵「DB 降級為純 queue、parse 之後全是讀檔寫檔的純函數」
是 Phase 4 的**本體**，且觸發式、可能永遠只走一部分——三個目標最痛的部分
（靜默失敗、協作門檻、多 vendor、橫向擴展）Phase 1–3 已解掉，Phase 4 剩的
主要是費用與全歷史 re-parse 便利。「不做 big-bang」約束的是遷移方式而非
終點：**路線上每一格都是完整可運作的系統**，停在任何一格收工都不是半套。

---

## 三、四個分類軸

### A. 執行層：queue 顯式狀態機＋單一 flow 定義

**現況**：`RequestTS`「刪列＝完成」，失敗只能事後從殘留列推斷；errback 不寫
任何終結狀態，403 全滅時 spider 照樣「正常 finished」；編排散在四套機制。
多 consumer 平行（`FOR UPDATE SKIP LOCKED` 認領）已驗證可行，是現成的
橫向擴展地基，缺的是**收工語意**。

**目標**：

1. queue 的生命週期是顯式狀態機 `pending → in_flight → done | failed(n) | dead`，
   **errback 必寫終結狀態**（失敗 → `failed`、attempts+1；超過上限 → `dead`）。
   「刪列＝完成」廢除。
2. 收工鐵律，finalize 斷言、不等就紅：

   > **seeds == terminals**：`done + dead == seeds`，且無 `pending / in_flight / failed` 殘留。

   這一條不變量能在**當下**抓到上述每一類事故（紅燈＋Slack、附 error 分類
   統計），而不是等 statscheck 事後驗屍。
3. 編排收斂成一個 make 式 DAG runner（`flow run --date … [--from <stage>]`，
   以「產出檔在不在」為完成判據）；**雲上與本機吃同一份 stage 定義**，
   差別只在 executor（本機 subprocess；雲上 detail stage＝開 N 個 ECS task
   搶同一個 queue）與速率參數。這個規模不需要 Dagster。

**具體改動（第一步不動架構）**：`request_ts` 加 `status / attempts / error`
三欄（一顆 migration）；spider errback 改寫狀態不刪列；go.sh／orchestrate
finalize 加斷言，紅 → 非零 exit＋Slack。

**不刪列的效能與容量對策**（設計時一併落地，避免表無限長）：現制的
問題不是「有刪除」而是「刪除承載完成語意」，新制把兩者拆開——
(a) 熱路徑用 partial index（`WHERE status IN ('pending','in_flight','failed')`），
終結列自動掉出索引，claim 掃描量只跟「當下未終結列」有關、與表總量無關；
(b) finalize 時終結統計（seeds／done／dead／error 分類）快照進當日
manifest，之後這些列只剩 debug 價值——套既有滾動窗口哲學保留 N 天
（比照 raw 的 90 天），窗口外每日批次 DELETE。**「何時刪」從正確性條件
降級為清理政策**，早刪晚刪都不影響對帳。

### B. 觀測層：manifest 作為階段間契約

**現況**：品質觀測是四套工具、四種 baseline 格式——statscheck（當日）、
fill-rate monitor＋baselines（填充率）、distcheck＋national.json（分佈
不變量）、monthreport（月窗）。survey 層與 DB 層兩套量法並存，baseline
重製要先解「量法不一致」。

**目標**：一個機制——**每個 stage 自動產出 manifest**（進出筆數、逐欄
填充率、錯誤分類、分佈統計、queue 終結統計、耗時、版本），品質門檻＝
repo 版本化的斷言檔（`quality/assertions.yaml`）對 manifest 的斷言集。
日檢、月報、漂移偵測只是同一機制的不同時間窗：

| 現制 | 收斂後 |
|---|---|
| statscheck | detail／parse manifest 的當日斷言 |
| fill-rate monitor＋baselines | `fill_rate.*` 斷言（ref 用滾動中位數；兩套量法的分歧天生不存在） |
| distcheck＋national.json | `dist.*` 斷言 |
| monthreport | 同一批 manifest 疊月窗（缺爬日＝該日 manifest 不存在） |

告警單一通道：`[stage] 斷言名 觀測值 vs 門檻＋manifest 連結`。
「哪裡壞、壞多少」不再需要人肉翻 log 交叉比對。這也是 ai-triage 的
理想證據包格式（結構化、無個資、可直接上 GitHub issue）。

### C. 資料層：raw 出 DB → 漸進 artifact 化

**現況**：案 A（90 天滾動 offload，housekeep 排程化）已上線，DB 成長受控。
案 B（pipeline 直寫 S3、DB 不存 raw）在 aws-deployment-plan 列 Backlog。

**目標**：案 A 跑順後推進**案 B**——pipeline 直寫當日
`raw/<vendor>/<date>.tar.zst`＋index，DB 從此不存 raw；rerun 工具改讀
S3 index。收益：DB 體積成長歸零、rawoffload／housekeep 退役、
「歷史 raw」與「當日 raw」同一格式（遷移／歸檔概念消失）。

再往後的 parquet 化（snapshot／deals 出 DB、RDS 降級為純 queue、
DuckDB 掃分區做分析）**留給明確觸發點**：591 再改版逼全歷史 re-parse、
或 RDS 費用重新變成痛點。屆時一個 stage 一個 stage 換，不是一次翻掉。

### D. 協作層：vendor 即 plugin＋monorepo＋貢獻者迴路

**現況**：`RentalSpider` contract 本來就 vendor 中立、出貨端天生多來源、
fixture／scrub 方法論已成文、`twrh` CLI 讓 parser 開發不碰 DB——資產
大半到位（見 multi-vendor-plan〈已經到位的資產〉）。缺的是把「591 專用」
的部分一般化，以及兩包分裂（改 core 要先發版才能在 dataset 驗）。

**目標**：

1. **Vendor Protocol——介面用資料契約定義**，貢獻者只碰四個函數＋fixtures：

   ```python
   class Vendor(Protocol):
       name: str
       def list_requests(self, region) -> Iterable[FetchSpec]: ...
       def parse_list(self, body: bytes) -> list[ListingStub] | VendorError: ...
       def detail_request(self, stub: ListingStub) -> FetchSpec: ...
       def parse_detail(self, body: bytes) -> NormalizedRecord | VendorError: ...
   ```

   搭配 **conformance kit**（`twrh vendor check <name>`）：fixtures 全過
   golden test（scrub 標準沿用 `tests/fixtures/README.md`）、fill-rate 不低於
   該 vendor 的 baseline、enum 對映只 append 不改值（CI diff 擋）。
   新 vendor＝實作介面＋跑過 kit，完全不需要理解 queue／snapshot／export。

2. **monorepo 收攏兩包**：程式碼收成 workspace（`core/`、`pipeline/`、
   `vendors/<name>/`、`quality/`、`ui/`、`tools/`），PyPI 套件是 build
   artifact 而非獨立開發維度——「改 core 要先發版」與 enums 漂移這類問題
   從結構上消失。**倫理分界不變**：速率、排程、風控參數在部署層
   （tfvars／.env），永不入版控。

   **對外契約不因收攏退化**（2026-09-03 查證後補）：「爬蟲歸爬蟲、
   其他人可拿去做其他用途」的原始目標有真實（雖小而安靜的）外部使用者
   ——公開專案曾宣告依賴（rentea-crawler 等）、有人整包 source 搬走用、
   且今年有外部貢獻者實際回報並修復 parser。收攏改的是**內部開發結構**，
   以下對外承諾不變：`pip install` 可用、套件自帶獨立 README／examples、
   版號語意照舊；套件目錄保持自足可讀、可整包帶走。

3. **貢獻者三迴路**（參與門檻的實際形狀）：
   - **parser 迴路**（最大宗）：`twrh` CLI＋fixtures＋離線 pytest，
     零 DB、零雲、零 token——已存在，P1 加上 vendor 維度。
   - **pipeline 迴路**：dataset 側測試 A 層（deal 狀態機、月報紅綠等純邏輯，
     不需 DB）與 B 層（queue 語意矩陣，CI 掛 Postgres）；長期由
     「sync 幾天分區檔案」取代「自建 PostGIS」成為開發環境。
   - **UI 迴路**：已獨立（Astro，npm 三指令），不受本計畫影響。

---

## 四、分階段

排序依據＝依賴關係與觸發條件，不是痛感。每一步獨立有收益、可獨立驗收。

### Phase 1 — 地基：讓靜默失敗絕種（現在可動）

| # | 事項 | 具體動作 | 規模 | 驗收 |
|---|---|---|---|---|
| 1-1 | **seeds==terminals**（軸 A 第一步） | `request_ts` 加 `status/attempts/error` 欄；errback 改寫終結狀態不刪列；go.sh／orchestrate finalize 加斷言，紅 → 非零 exit＋Slack（含 error 分類統計） | 1–2 天 | 以歷次靜默失敗場景重演（403 全滅、seed 零產出）：finalize 當場紅 |
| 1-2 | **manifest 統一**（軸 B） | statscheck／fill-rate／distcheck 輸出合併為 `manifests/<date>/<stage>.json`＋`quality/assertions.yaml`；與舊通道平行跑一週後切換；monthreport 改讀同批 manifest | 2–3 天 | 四套工具退役、Slack 只剩一條通道 |
| 1-3 | **既有收尾直接做在新格式上** | baseline 重製（dx-roadmap Backlog 既定 9/5 項）落在 assertions.yaml；L-C 語意公告、refresh_days 校準照 dx-roadmap 收尾 | 隨 1-2 | 不產生第五套 baseline 格式 |

1-1＋1-2 做完，「靜默失敗」類事故從結構上絕種——這是四個目標裡現在
離得最遠的一個，也是後面每一步的安全網。

### Phase 2 — 多平台前置（由 #29 觸發；＝multi-vendor-plan P0／P1 的實作面）

| # | 事項 | 具體動作 | 規模 |
|---|---|---|---|
| 2-1 | Vendor Protocol＋conformance kit | 介面落地（591 是第一個實作者，重構即驗證）；`twrh vendor check` | 中 |
| 2-2 | 591 專用件一般化 | enums 拆 shared vs vendor-specific（編碼值治理：只 append）；`twrh` CLI 加 vendor 維度；baseline／哨兵 per-vendor 化 | 中 |
| 2-3 | dataset 側測試 A／B 層 | A：deal 狀態機等純邏輯；B：queue 認領／釋放／batch／seed 矩陣（CI 掛 Postgres）——queue 是歷史上 bug 密度最高的共用件，開放共用前的安全網，也是 1-1 重構自身的安全網 | 中 |
| 2-4 | **monorepo 收攏** | 與 2-1 同動、不單獨做：workspace 佈局、PyPI 套件改為 build artifact、dev-core.sh 退役 | 大 |

備註：2-3 的 B 層與 1-1 有互相增強關係——若 #29 動工在前，B 層可提前到
Phase 1 一起做；順序由觸發時點決定，不硬性綁死。

### Phase 3 — 資料層與執行層收斂（等 Phase 1 跑順）

| # | 事項 | 具體動作 | 規模 | 驗收 |
|---|---|---|---|---|
| 3-1 | **raw 出 DB（案 B）** | pipeline 直寫當日 `raw/<vendor>/<date>.tar.zst`＋index；rerun 工具改讀 S3；DB 不再存 raw | 3–5 天 | DB 體積成長歸零；rawoffload／housekeep 退役 |
| 3-2 | **flow 收斂四套編排** | make 式 DAG runner；go.sh／orchestrate.sh／batch marker／progress 檔四合一；本機與雲上同一份 stage 定義、executor 可換 | 中 | 一條指令可從任一 stage 續跑本機或雲上 pipeline |
| 3-3 | 開發環境零雲相依 | `s3 sync` 數日分區即可跑 pipeline 後段（parse 之後不需連網／DB raw） | 小 | 新貢獻者不建 PostGIS 也能跑資料後段 |

### Phase 4 — 觸發式（明定觸發條件，不排程）

| 事項 | 觸發條件 |
|---|---|
| snapshot／deals parquet 化、RDS 降級為純 queue（SQLite-on-EFS 或極小 Postgres）、DuckDB 分析工作流 | 591 大改版逼全歷史 re-parse，或 RDS 費用重新成為痛點 |
| AI triage A1／A2（告警自動開 issue、核准後自動修 PR） | Phase 1 的 manifest 告警就位後（manifest 即證據包）；見 `docs/ai-triage.md` |
| 第二個 vendor 之後的規模化（新增 vendor 指南、issue 模板、發版節奏文件） | multi-vendor P2，第一個新站走通後 |

---

## 五、與既有 docs 的對照（本計畫吃掉誰、依賴誰）

| 既有文件 | 關係 |
|---|---|
| `dx-roadmap.md` | 已收線（Phase 0–4＋L-A/B/C 完成）。其 2.5-3 指涉的「queue 顯式終結狀態」設計＝本文 1-1；Backlog 的 baseline 重製＝本文 1-3；4-6 多站點抽象＝本文 Phase 2。收尾項照原計畫走，不搬進來 |
| `multi-vendor-plan.md` | 其 P0（流程與治理）維持原文件；P1（架構解耦）的實作形狀＝本文 Phase 2；P2＝本文 Phase 4 |
| `aws-deployment-plan.md` | 基礎設施幾乎不變（Fargate＋EventBridge＋micro RDS 已接近此預算正解）；其 Backlog 案 B＝本文 3-1；剩餘 publisher 雲化與本計畫無相依、照原計畫走 |
| `export-automation-plan.md` | 出貨端不變（export／publish.sh／紅綠分岔照舊）；monthreport 在 1-2 改讀 manifest，紅綠語意不變 |
| `monthly-insights-plan.md` | 無相依。其「對月 zip 用 columnar 引擎掃、不碰 DB」的計算形狀與本文 Phase 4 的分析工作流同方向，屆時自然合流 |
| `ai-triage.md` | 本文 1-2 的 manifest 是其 A1 需要的結構化證據包；A0 隨時可做，A1/A2 排 Phase 4 |
| `ui-roadmap.md` | 無相依，分開排程（既定原則） |

---

## 六、建議不做

| 項目 | 理由 |
|---|---|
| **big-bang 重寫** | 這個月的 probe／harvest／baselines／distcheck／monthreport／orchestrate／L-C 已在朝目標形狀演化，全部打掉重寫性價比為負。逐項偷回來，每步獨立有收益 |
| **引入 Dagster／Airflow 級 DAG 平台** | 一天一輪、六個 stage 的量級，「以 artifact 存在為完成判據」的 make 式 runner 就夠；平台是平移複雜度不是消除 |
| **現在就 parquet 化 snapshot／deals** | 沒有觸發點（re-parse 需求、RDS 費用痛點）之前，收益不抵遷移成本與心智轉換（invalidate 類「回頭修歷史」變成重寫分區＋重建下游）。留給 Phase 4 |
| **csv-aggregator 換 DuckDB** | clickhouse local 已對「公開資料集去重語意」驗證過、每年只跑十幾次；port 要重驗 byte 級等價，收益趨近零 |
| **在第二個 vendor 出現前做 monorepo 收攏** | 沒有第二個實作者時的 workspace 邊界是猜的；與 2-1 同動才有驗證對象（dx-roadmap 4-6 的既定原則） |
| **queue 換訊息佇列（SQS 等）** | 「認領＋終結狀態＋收工對帳」需要的是可查詢的表，不是 at-least-once 投遞；SQS 反而做不到 seeds==terminals 對帳 |
| **為橫向擴展預先拆微服務** | 擴展軸（worker 數、vendor 數）都已由 queue 表與 Vendor Protocol 承載；行程邊界不是瓶頸 |

---

## 附錄：儲存演變對照（每步做完後 DB／FS／S3 的差異）

「—」＝不變；每列為**該步新增的差異**，累積於上一列之上。Phase 4 依
北極星六 stage 拆成可獨立觸發的子任務（4a–4e），順序可被觸發點抽換
（例如 re-parse 需求只逼出 4b）；唯一硬依賴＝4e 須等 4b–4d 完成。

| 階段／任務 | DB（RDS） | FS（EFS／本機） | S3 |
|---|---|---|---|
| 現況（基準） | House／HouseTS（90 天窗）／HouseEtc（raw 90 天窗＋detail_dict 全量）／RequestTS（刪列＝完成）／Stats | `logs/`＋progress json＋fill-rates、`datas/` 月 zip＋publish state、月報 json；repo 內 `baselines/` | `publish/` 公開 zip；housekeep 月度 raw 包＋TS 歸檔 tgz；logs 歸檔 |
| Phase 1 | `request_ts` ＋`status/attempts/error`，終結列留存、滾動清理；Stats 停止新增（職責交 manifest） | fill-rates／distcheck history 停產；repo ＋`quality/assertions.yaml`、`baselines/` 退役 | ＋`manifests/<date>/<stage>.json` |
| Phase 2 | — | —（repo 佈局改 workspace；per-vendor baseline 進 `vendors/<name>/`） | — |
| 3-1 raw 出 DB | `detail_raw`／`list_raw` 停寫並清空——DB 成長歸零 | — | `raw/<vendor>/<date>.tar.zst`＋index 改每日直寫；housekeep raw 半邊退役 |
| 3-2 flow 收斂 | — | progress json／stop marker／log-grep 契約退役——完成判據＝產出檔存在 | — |
| 3-3 零雲相依 | 本機 PostGIS 降為 queue／爬取段才需要 | 開發機 `s3 sync` 分區即可跑 parse 之後段 | — |
| 4a list 檔案化 | `HouseEtc.list_dict` 停寫 | — | ＋`list/<vendor>/<date>.jsonl.zst` |
| 4b parsed parquet | `detail_dict` 停寫——`house_etc` 退役；rerun 工具退役 | — | ＋`parsed/<vendor>/<date>.parquet` |
| 4c snapshot parquet | `house_ts` 退役；`synthts` 消失（carry 併入 stage 定義）——housekeep 整支退役 | — | ＋`snapshot/<date>.parquet`（取代 TS 歸檔 tgz） |
| 4d deals parquet | deal 推導出 DB（`syncstateful` 退役）——`house` 退役（現值＝最新 snapshot） | — | ＋`deals/<date>.parquet` |
| 4e RDS 降級純 queue | RDS 只剩 queue 一張表，或換 SQLite-on-EFS（單寫者 $0）；export／statscheck 改 DuckDB 掃 S3 | queue 為 SQLite 時 `.db` 住 EFS | 成為唯一真相來源（北極星全樹到齊） |

讀表要點：DB 欄的走向＝「先停止長大（3-1）→ 逐表退役（4b–4d）→ 只剩
queue（4e）」，且每一步 DB 少掉的那塊都有一個工具同時退役（rerun／
synthts／syncstateful／housekeep）——維護面積隨儲存收斂；S3 欄即北極星
那棵樹的生長順序。

---

## 編修紀錄

- **2026-09-03（四補）** 新增附錄〈儲存演變對照〉：各 phase 與 Phase 4
  子任務（4a–4e）對 DB／FS／S3 的差異、工具退役對應、子任務觸發順序
  可抽換原則（硬依賴僅 4e←4b–4d）。
- **2026-09-03（三補）** 北極星節補「殼 vs 本體」對應（Phase 1–3＝殼、
  Phase 4＝本體且觸發式；每格皆完整系統）——回應「做到 Phase 3/4 是否
  等於北極星」的釐清。
- **2026-09-03（二補）** 2-4 補對外契約條款：查證外部使用
  （公開依賴專案、source 整包再利用、外部貢獻者）後，明訂 PyPI 套件
  承諾不因 monorepo 收攏退化。
- **2026-09-03（補）** 依維護者回饋補 1-1 的「不刪列」效能對策
  （partial index＋manifest 快照後滾動清理，刪除從語意降級為清理政策）。
- **2026-09-03** Claude 起草。整併 repo 外兩篇 redo-design 筆記的結構性結論
  （量測數據依慣例省略）、docs/ 七份計畫現況、與 2026-08 以來的事故經驗；
  五步「偷回來」路線中 list-driven 成交偵測（L-C）已完成，其餘四步落入
  本文 Phase 1–3。尚未經維護者 review。
