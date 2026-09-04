# 架構演進計畫（好維護・橫向擴展・模組可抽換）

> **狀態**：本文件由 Claude 起草（2026-09-03），已經維護者多輪 review 拍板
> （見〈開放問題〉與〈編修紀錄〉）；Phase 1＋3 程式面已併入 master、部署
> 階梯進行中（見〈實作狀態〉）。內容仍會隨部署與實跑回饋修訂；歡迎以
> issue / PR 回饋。
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
   （終局連這個例外也消掉：seeds 事先已知，queue 退化為「seeds 檔＋
   每 worker 一份 append-only 終結紀錄」，不需要任何 server——見
   〈開放問題・已拍板〉2026-09-04 項。Phase 1–3 仍用表，因為 DB 此時
   還是 House／HouseTS 的真相，queue 只是搭便車。）
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

**schema 演進紀律**（跨年分區並存的規則）：三層分界——raw 無 schema
永不遷移；vendor parse 中間產物（現制 detail_dict）**不再持久化**，
降為 parse stage 行程內中間值，591 改版打到的是 vendor plugin 程式碼
而非任何落地資料；`parsed/`／stubs 落地的是我們控制的 normalized 契約，
與站方版式解耦。契約演進兩條路：(a) **只增不改**（同 enum 治理）——
新欄位 nullable append、改語意＝新欄位＋棄用標記，讀取端
`union_by_name` 掃跨年分區、舊分區自動補 NULL，並存無害；(b) breaking
change **不寫 migration、用重算**——raw 都在，`--from parse` 重寫
歷史分區＋下游依 DAG 重建。每列帶 `parser_version`、manifest 記
schema 版本；**歷史重算永遠由人顯式觸發**（版本對比決定回溯深度），
不做 make 式 mtime 自動級聯——避免 parser 改一行自動重算全歷史。
推論出的補強：**list raw 也應按日落地 `raw/`**（list 頁均長極小、
成本可忽略），否則 stub 層沒有「回頭多抓一欄」的重算保險——
591 版式改版的兜底就不完整。

**S3 治理：無定期清理**：現制清理工作（rawoffload／archivehistory／
housekeep）存在的理由全是 RDS 的物理性質（貴、只長不縮、容量影響效能）；
S3 上全部分區的年增量在 Glacier IR 單價下成本可忽略，「為容量刪東西」
沒有標的。需要的只有兩條 set-once lifecycle 規則（terraform，一次寫定，
非排程 job）：raw 30 天轉 Glacier IR；若開 versioning，非當前版本
N 天過期（「重算取代 migration」的配套，與壓縮框架同在 3-1 拍板——
或不開 versioning、重寫即覆蓋）。唯一的定期刪除是**政策性**的——
**raw 保留 365 天（2026-09-03 拍板）**：lifecycle expiration 一條規則
（仍是 set-once，非排程 job），個資／著作權暴露面從永存變有界。
配套設計使 365 天能乾淨地只套用於 raw：stub 指紋存**雜湊**而非 title
原文、normalized 分區本就不含 title／description——事件分區與 snapshot
不含個資／著作權內容、永存，replay 與 snapshot 重建不受 raw 過期影響。
代價＝breaking-change re-parse 回看上限一年，更早歷史以 normalized
分區＋公開 zip 為準——與現實一致（pre-2024 raw 已佚失且被接受，
rerun 實務回看深度＝parser bug 發現延遲，遠短於一年）。

**存取模式分層**（格式選擇的依據）：(1) 高頻點查（queue claim）留在
DB——唯一可變狀態不進檔案的另一面；(2) 單屋跨日歷史點查是已承認的
退化項，緩解＝parquet 分區內按 house_id 排序、靠 row-group 統計跳讀
（秒級），常查再物化本機 DuckDB；(3) jsonl 只用在「整檔掃描是唯一
熱路徑」的小檔（list stubs、manifest），若分析量變大，stage 產出格式
是契約後的實作細節、可換 parquet。唯一需要 random access 的 jsonl 是
`raw/` 的 index（debug 點查單頁 HTML），而 tar.zst 整流壓縮下 offset
無法直接跳——**已拍板整包拉回（2026-09-03）**：不採可尋址壓縮、
不依賴 S3 特有功能，debug 點查＝拉當日包（百 MB 級可接受），
單流壓縮率最佳、換任何 object storage 都成立。

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

### 案例對照：L-C（list 驅動 detail 降頻）在新架構的形狀

以最近完成的 L-A/B/C 為試金石——它同時踩到四個軸，新架構讓它從
「後補的 diff 模式＋一支補丁指令」變成「預設語意＋一個純函數」：

| 現制機制 | 新架構落點 |
|---|---|
| L-A 翻頁邏輯 | 不變，住在 vendor plugin 的 `list_requests`／`parse_list` |
| `list_dict`／`list_crawled_at` 欄位 | 消失——`list/<date>.jsonl.zst` stub 檔即完整紀錄 |
| 指紋比對＋`list_fingerprint_changed_at` | stub 自帶 `fingerprint` 欄（vendor 的 `parse_list` 正規化產出）；「上次指紋」＝昨日 stub 檔 |
| `seed_mode=diff` skip 謂詞（散在三處 DB 狀態） | **seed 推導＝純函數**：今日 list＋前 N 日 list＋昨日 snapshot 三組檔案 → 四類 seeds（stale／指紋變／連續缺席／回列）→ 寫 queue |
| `synthts`＋`is_synthesized` | 整支消失——snapshot stage 定義即 carry（`source=carry` 欄） |
| 缺席 ≥2 天、`refresh_days`、回列窗口 | 政策參數進 `quality/`，per-vendor 可覆寫 |
| `Stats.n_open_in_list` 哨兵 | 一行斷言：昨日 snapshot OPENED ∩ 今日 stubs 比率，入 list manifest |
| 收斂驗證（人工 DB query） | detail manifest 自帶 `seeds_by_class`／`skipped`，疊時間窗即收斂曲線 |

純函數化的三個紅利：**離線可測**（fixture 檔即可測四類 seeds 的邊界
情況，不需 DB）；**可稽核**（list 檔不可變，對任何歷史日重算 seed 函數
即重現當天決策——L-B 式誤殺率實驗不再需要重掃站方）；**多 vendor 免費**
（降頻做在 `ListingStub` 契約上，新 vendor 的 `parse_list` 產得出帶指紋
的 stub 就自動獲得整套機制）。

兩條實驗換來的判準原封保留：狀態變更永遠由 detail 判定（缺席只是種子）；
bootstrap 自然退化為全量、逐日收斂——行為語意與儲存形狀無關。

**snapshot 即摺疊狀態（冷啟同步深度＝1 天）**：謂詞所需的 per-house
滾動狀態全部摺進 snapshot 當 carry 欄——`last_detail_at`（refresh_days）、
`fingerprint_at_last_detail`（指紋變）、`days_absent`（連續缺席計數，
免回掃 N 天 list 檔）、`last_seen_at`（回列窗口）、`first_seen_at`＋
sticky deal 狀態（n_day_deal）。**每日運行因此是一階遞迴**
`f(昨日 snapshot, 今日輸入)`：新環境冷啟只需 sync 昨日一份 snapshot，
不隨 refresh_days 或 deal 回看深度放大；現制的 90 天窗口是「DB 保留
窗口」的產物，新架構歷史分區永存、回看深度與同步深度脫鉤。重建
snapshot（fold 邏輯改動或 carry 欄修錯）＝從任一舊 checkpoint replay
事件分區，深度是修復決策而非環境需求。代價與緩解：carry 欄 bug 會
向前傳播——manifest 對 carry 欄分佈下斷言，且事件分區永存保證隨時
可 replay 重建（現制 House 覆寫後連 replay 原料都沒有）。

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
| snapshot／deals parquet 化、queue 出 DB（檔案化靜態分片，RDS 退役）、DuckDB 分析工作流 | 591 大改版逼全歷史 re-parse，或 RDS 費用重新成為痛點 |
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
| **queue 換訊息佇列（SQS 等）** | 「認領＋終結狀態＋收工對帳」需要的是可查詢的紀錄，不是 at-least-once 投遞；SQS 反而做不到 seeds==terminals 對帳。終局形狀（檔案化靜態分片）同樣滿足對帳且不需 server，見已拍板 2026-09-04 項 |
| **SQLite-on-EFS 給多 worker 共用** | NFS 檔案鎖不可靠，多寫者 claim 是已知地雷；只在單寫者成立。真要多 worker，走「每 worker 一檔」佈局——到那時 jsonl 就夠，SQLite 也沒必要 |
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
| 4e queue 出 DB、RDS 退役 | `request_ts` 退役——queue 改為 seeds 檔＋每 worker 一份終結紀錄（檔案化靜態分片，見已拍板 2026-09-04 項），DB 歸零；export／statscheck 改 DuckDB 掃 S3 | `seeds/<date>.jsonl`＋`terminals/<date>/run-<k>/worker-<i>.jsonl` 住 EFS scratch，finalize 併入 manifest | 成為唯一真相來源（北極星全樹到齊） |

讀表要點：DB 欄的走向＝「先停止長大（3-1）→ 逐表退役（4b–4d）→ 歸零
（4e，queue 也出 DB）」，且每一步 DB 少掉的那塊都有一個工具同時退役
（rerun／synthts／syncstateful／housekeep／request_ts 表）——維護面積
隨儲存收斂；S3 欄即北極星那棵樹的生長順序。

---

## 開放問題

### 已拍板（2026-09-03，二輪 review）

- **raw 保留 365 天**（S3 治理節）；**snapshot 承載摺疊狀態**（L-C 案例
  節）；**stub 指紋存雜湊**。
- **raw 壓縮框架＝整包拉回**：不採可尋址壓縮、不依賴 S3 特有功能；
  單流壓縮率最佳、可攜性最好，debug 點查＝拉當日包（百 MB 級可接受）。
- **versioning 不開**：重寫分區即覆蓋，兜底＝「365 天內可重算」本身。
- **動態基準＝疊窗即算**：斷言引擎當場掃近 30 份 manifest（KB 級），
  不物化第二種 baseline artifact——觀測層單一機制原則的延伸；history
  不足 N 天（bootstrap 期）該類斷言自動降 advisory。
- **可散佈界線與存取**：S3 樹全私有（公開僅 `publish/`）；可散佈界線
  切在 normalized，但 normalized 分區**原則上不公開釋出**（著作權
  顧慮）；一般貢獻者以 `twrh` CLI 自抓資料開發；簽署相關同意條款的
  專案成員，才議定分區釋出管道——與現制同構（公開僅 publish zip、
  開發迴路靠 CLI），只是明文化到 bucket 權限。
- **切換與對帳＝非開放問題**，併入各步驗收（Phase 1 平行週、3-1 雙寫
  對帳、其餘由 bootstrap 語意吸收）；唯一具名產物＝4c/4d 切換日從
  現制 DB 摺出歷史 sticky 狀態（first_seen、deal 史——bootstrap 長
  不回來、會使 n_day_deal 歸零）的一次性工具。
- **日期 pin＝3-2 實作註記**：flow `--date` 是唯一日期來源，所有 stage
  收參數、**禁止 stage 內部看時鐘**——現制 env 隱式傳遞的結構化修正
  （export 曾漏讀 TWRH_TARGET_DATE 即此類 bug，跨午夜才發作）；
  `--start-early` 上移排程層（22:00 後的排程直接傳明日 date）；bucket
  歸屬走 pin 日期、記錄型時間戳（seen_at）記真實時刻，兩者明文分開。
  剩現制讀 env 五處（rental.models／now_tuple／persist_queue／
  syncstateful／statscheck）的盤點替換，機械工作。

- **多 worker artifact 佈局＝方案 A**（2026-09-03 拍板）：worker 落
  EFS scratch、finalize 單一打包上傳——一日一檔、完成判據純粹、壓縮率
  最佳、與單機模式同構；代價（收尾分鐘級打包、crash 後 scratch 清理
  ——重跑覆蓋即可）接受。落選 (B) 逐 worker 小包：一日 N 檔滲進所有
  下游、完成判據退化為 manifest 記載清單。
- **invalidate＝訂正疊加層**（2026-09-03 拍板）：invalidate 產出本身
  是 artifact（house_id＋影響範圍＋判定理由），歷史分區一 byte 不動，
  export／統計讀取時 join 排除——帳本模型（訂正用追加不用改寫）：
  可稽核、可撤銷、判定邏輯改版只需重出名單；判定邏輯（跨日欄位
  穩定性）平移自現制。落選 (a) 重寫歷史分區：動作大且原始證據被改寫。
- **Phase 1＋3 開發環境分工**（2026-09-03 拍板）：AWS 續跑現制日更並
  觀察 L-C 收斂；本機另起全新 DB（複製近 14 天＋vendors fixture）作
  新架構開發場——本機 DB 不再視為 production 副本，本機接手 ramp-up
  凍結。驗證與部署皆逐步：本機驗過一步、AWS migrate 一步，不攢包
  切換；AWS 每步部署 pin commit、記於編修紀錄。Phase 2 順延至 1＋3
  部署完（新站踩點、fixture 蒐集可先行）。
- **config 全走 env（1-0 前置）**：`settings_local.py` 退場、不留
  fallback——DATABASES／SENTRY_DSN／SLACK_WEBHOOK_URL 併入 .env 體系，
  兩地部署同步改。本機實驗關 Slack／Sentry；3-1 產出先寫本機目錄，
  production bucket 留給 AWS 雙寫對帳階段。
- **舊 raw 月包不回整**：3-1 上線日即界線日——界線前的 housekeep
  月度 raw 包維持原格式（僅 debug 價值），不重整為按日分區；raw
  365 天／Glacier IR lifecycle 規則（軸 C 既拍板）與 3-1 同步落地
  terraform。
- **9 月 manifest 由 DB 回補**：1-3 附帶一次性 backfill——從 DB 重算
  9 月已爬日的 manifest（筆數／fill-rate／分佈皆可重算，manifest 本是
  對資料的純函數；queue 終結統計因「刪列＝完成」已丟，缺項標
  `source=backfill`、該類斷言降 advisory），使 monthreport 的 9 月窗
  全走新格式、不跨兩制。9/5 的 baseline 重製順延至 1-2 完成後
  （落 assertions.yaml，不產第五套格式）。
- **2-3 B 層提前**：queue 語意測試矩陣與 1-1 同做（原備註的觸發
  成立——它同時是 1-1 重構自身的安全網）。
- **queue 終局＝檔案化靜態分片，不需 server**（2026-09-04 拍板，
  落點 4e）：Postgres 被選上只因 `FOR UPDATE SKIP LOCKED` 順手，
  queue 真正的需求只有三條——N 個 worker 不重複、每筆有顯式終結狀態、
  收工能算 seeds==terminals——而 pipeline 一天只跑幾小時，為此養一台
  DB server 不划算。北極星裡 seeds 由 list stage 之後的純函數一次算出、
  事先已知，因此「認領」這個動作本身不需要：
  - **分片**：worker i 對「剩餘集合」排序後依位置輪流分（不用
    `hash % N`——剩餘集合小時取模明顯不均，位置輪分精確均等且所有
    worker 無通訊算出同一結果）；首輪的剩餘集合就是 seeds 本身。
  - **記帳按 house_id 不按 worker**：每個 worker 只寫自己的 append-only
    終結檔 `terminals/<date>/run-<k>/worker-<i>.jsonl`（done／failed／
    dead，每行帶 attempts），單寫者、無鎖，EFS 上安全。沒有 in_flight
    狀態——「未終結」即「還要做」，crash 當下的請求自然重做，現制
    「殘留 in_flight 要人清」的問題不存在。
  - **續跑可改 N、不需各 worker 進度一致**：新一輪每個 worker 讀當日
    **全部**終結檔（這步不能省），聯集即已終結集合，剩餘＝seeds 減
    已終結（done、dead、attempts 達上限的 failed），再對剩餘集合重新
    分片；舊進度多不均都只影響剩餘集合長什麼樣。新一輪寫新一代
    `run-<k+1>/`，永不接續別人的檔。attempts 跨檔累計（取該 house
    最大值往下加），否則改 N 重跑會把重試計數歸零、dead 永遠出不來。
  - **primary 整理 checkpoint 是最佳化不是正確性條件**：可把各 shard
    併成 `checkpoint.jsonl` 加速啟動，但**只增不刪**（原 shard 留著，
    舊 worker 沒死透補寫也不丟）；舊新 worker 撞同一戶只是多抓一次，
    finalize 按 house_id 去重取最終狀態，不會算錯帳。以本專案量級
    （一日數萬 seed、MB 級檔案）全讀比整理便宜，先不做 checkpoint。
  - **finalize**：合併所有世代、按 house_id 去重，seeds==terminals
    變成算行數，結果直接就是 detail manifest 的 queue 終結統計。
  - 代價：無動態 work-stealing——worker 同質、瓶頸在站方而非 worker，
    影響可忽略。若日後被證明不夠，動態認領的 serverless 解是
    DynamoDB 條件式 UpdateItem（按請求計費、閒置零成本），但引入 AWS
    專屬相依、本機要跑 DynamoDB Local，與可攜性原則有衝突，列為
    備案不列為路線。
  - 過渡期（Phase 1–3）不動：DB 仍是 House／HouseTS 真相，queue 只是
    搭便車，單獨換沒有收益。若只為省閒置費，便宜解＝RDS 排程
    stop／start（EventBridge 前後各觸發一次），或 Postgres 當 ECS
    sidecar、資料目錄放 EFS 讓 RDS 先退場。

### 仍開放

| # | 問題 | 歸屬 |
|---|---|---|
| 6 | **deals 語意 × #229**：成交訊號消失調查的結論影響事件類別設計（DEAL／NOT_FOUND／原因不明下架） | 調查先行 |
| 8 | **queue 清理窗口長度**：預設 90 天，實跑後定案 | Phase 1 |

---

## 實作狀態（2026-09-04 更新）

Phase 1＋3 全部程式面完成（分支 `arch-phase1-3`，已併入 master）、本機
開發場驗證通過；部署照拍板逐步走，每步 pin commit。部署階梯與日曆門檻：

| 步 | 內容 | 門檻 |
|---|---|---|
| D1 | 1-1＋B 層：`request_ts` migration＋errback 終結狀態＋queuefinalize | 唯一一顆 RDS migration（純加欄，向後相容） |
| D2 | 1-2 平行模式：manifest＋qualitycheck 與四套舊工具並行 | — |
| D3 | 1-2 切換：退役 statscheck Slack／distcheck／fill-rate ext；Stats 凍結（已查無其他消費者）；baseline 重製落 assertions.yaml | **平行期滿**——原定一週，2026-09-03 改為「連續 3 天逐項一致即切」 |
| D4 | 3-1 雙寫：rawpack 上 S3＋terraform lifecycle（raw/ 30d Glacier IR＋365d 過期） | terraform apply |
| D5 | 3-1 切換：DB 停寫 raw＋一次性清空；rawpack 失敗升硬紅；rawoffload／housekeep raw 半邊退役 | **雙寫對帳數日** |
| D6 | 3-2：flow.py 取代 go.sh／orchestrate（EventBridge 改指 flow）；驗 ecs executor | flow 於 AWS 驗過 |

部署紀錄（每步 pin commit，依拍板記於此）：

| 日期 | 步 | 內容 | pin |
|---|---|---|---|
| 2026-09-03 晚 | D1＋D2＋D4 | RDS migration 0005（純加欄，適逢 `request_ts` 全空）；terraform task def rev 7（EFS 路徑 env、raw lifecycle 30d Glacier IR／365d 過期、manifests IAM）；run-task 回補 9/1–9/3 manifest 進 EFS＋S3 | master `8f394a23` |
| 2026-09-04 凌晨 | 首跑驗收 | queuefinalize production 首次對帳一次過（全 done、零 dead 零殘留）；qualitycheck 全綠；日包落 `raw/591/`＋reconcile 抽樣一致；平行比對 Day 1 statscheck vs manifest 逐項一致。插曲兩件當夜收掉：rawpack 於 image 內 ModuleNotFoundError（raw 佈局實作移入 django 樹）、日包 vendor 目錄改短名對齊月包 | master `83b3f747` |
| 待 | D3 | 平行比對 9/4–9/6；9/5 baseline 重製落 assertions.yaml；三天一致即切 | — |
| 待 | D5 | 雙寫對帳數日後 cutover | — |
| 待 | D6 | flow ecs executor 於 AWS 驗過後切排程 | — |

附帶影響：**09-04 起本機不再日跑、202609 出貨源改 AWS**（2026-09-03
拍板）——月底雲上 `export -p` 產 zip；publisher 雲化的唯一設計項＝紅月
補 blog 時 `--resume` 的暫存 state 銜接（EFS 或 S3），月底前拍板，
記於 aws-deployment-plan。

實作備註：
- 驗收重演：403 全滅／殘留 → queuefinalize 當場紅（單元＋e2e）；
  seed 零產出 → 零種子紅；全 dead 也紅（dead 比率門檻，形式上
  seeds==terminals 仍不放行）。
- B 層矩陣 42 例（含並發認領、批次懸掛、seed 四類、斷言引擎），
  CI 掛 PostGIS（dataset-tests.yml）。
- 順手修：seed_only 同日重跑（queue 已空）不再全量重排——flow 續跑
  會踩的 2026-08-26 同型陷阱。
- 3-2 日期 pin：flow `--date` 單點寫入 env、`--start-early` 上移排程層
  已落地；「stage 收參數、五處 env 讀點替換」隨 Phase 4 各 stage
  檔案化時逐一收，env 傳遞在此前是唯一機制（偏離原註記，記錄在案）。
- 舊 rerun 工具（rerun_detail_raw/dict）實測早因改組失效；重放路徑
  由 tools/rerun_from_raws.py（讀日包）接手，DB 模式不再修。

## 編修紀錄

- **2026-09-04（補）** 狀態列改「已多輪 review、部署進行中」；〈實作狀態〉
  補部署紀錄表（D1＋D2＋D4 於 09-03 部署、09-04 首跑驗收、pin commit）、
  D3 門檻改「連續 3 天一致即切」、202609 出貨改 AWS 與 publisher 雲化
  設計項。
- **2026-09-04** queue 終局拍板：檔案化靜態分片（seeds 檔＋每 worker
  一份終結紀錄），不需 server；續跑可改 N、記帳按 house_id、attempts
  跨檔累計、checkpoint 只增不刪；4e 改為「queue 出 DB、RDS 退役」；
  建議不做加 SQLite-on-EFS 多寫者；DynamoDB 列備案、RDS stop／start
  列過渡期省費解。
- **2026-09-03（十四補）** Phase 1＋3 程式面全數完成（B 層→1-1→1-2→
  1-3→3-1→3-2→3-3，各自獨立 commit）；新增〈實作狀態〉節：部署階梯
  D1–D6、兩個日曆門檻（平行週、雙寫對帳）、驗收重演結果與偏離註記。
- **2026-09-03（十三補）** Phase 1＋3 開工拍板：雙環境分工（AWS 續跑
  現制、本機新 DB 當新架構開發場，本機接手 ramp-up 凍結）、config
  全走 env（settings_local 退場，列 1-0 前置）、舊 raw 月包取界線日
  不回整、9 月 manifest 由 DB 回補＋9/5 baseline 順延至 1-2 後、
  2-3 B 層提前與 1-1 同做、Phase 2 順延至 1＋3 部署完。
- **2026-09-03（十二補）** 末兩項拍板：多 worker 佈局＝方案 A（EFS
  scratch＋finalize 單包）、invalidate＝訂正疊加層。開放問題僅餘
  #6（deals×#229，調查先行）與 #8（queue 窗口，實跑定案）——
  **Phase 1 可動工**。
- **2026-09-03（十一補）** 開放問題二輪 review：拍板五項（壓縮框架＝
  整包拉回、versioning 不開、動態基準＝疊窗即算、可散佈界線＝normalized
  但原則不公開＋CLI 自抓＋成員條款、切換對帳併入各步驗收）；日期 pin
  降為 3-2 實作註記（顯式 --date、stage 禁看時鐘、start-early 上移
  排程層）；#1 補 A/B 優劣與建議 A、#5 補兩形狀與傾向訂正疊加層。
  仍開放四項：#1、#5、#6（#229）、#8。
- **2026-09-03（十補）** **raw 保留 365 天拍板**（lifecycle expiration，
  配套：stub 指紋改存雜湊使事件分區永存無虞、re-parse 回看上限一年）；
  新增〈開放問題〉節：十項，含多 worker artifact 佈局、私有／公開界線、
  切換對帳、invalidate 新形狀、deals×#229 等。
- **2026-09-03（九補）** 軸 C 補〈S3 治理：無定期清理〉：清理 job
  類別隨 housekeep 退役，僅剩 set-once lifecycle 兩條（Glacier IR 轉換、
  noncurrent version 過期）；唯一可能的定期刪除是個資政策項（raw
  預設永存、保留期限待拍板）。
- **2026-09-03（八補）** L-C 案例節補〈snapshot 即摺疊狀態〉：謂詞
  滾動狀態（last_detail_at／指紋／缺席計數／first_seen）摺入 snapshot
  carry 欄，日更為一階遞迴、冷啟同步深度＝1 天；90 天回看是 DB 保留
  窗口的產物，新架構回看深度與同步深度脫鉤，重建走 replay。
- **2026-09-03（七補）** 軸 C 補〈schema 演進紀律〉：三層分界（raw 無
  schema／vendor dict 不落地／normalized 契約只增不改）、breaking 用
  重算不用 migration、重算人為觸發不自動級聯；補強拍板項：list raw
  也按日落地，補齊 stub 層的重算保險。
- **2026-09-03（六補）** 軸 C 補〈存取模式分層〉：點查／掃描／jsonl 的
  格式歸屬原則；raw index 的 random access 前提（tar.zst 整流壓縮 vs
  可尋址壓縮）列為 3-1 day one 拍板項。
- **2026-09-03（五補）** 三之末新增〈案例對照：L-C 在新架構的形狀〉：
  diff 降頻從「後補模式＋synthts 補丁」變「seed 純函數＋snapshot carry
  語意」，離線可測／可稽核／多 vendor 免費；判準（detail 判官、bootstrap
  退化全量）原封保留。
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
