# 多資料來源（multi-vendor）準備計畫

> **狀態**：本文件目前由 Claude 起草，**尚未經維護者完整 review**，內容可能隨時變動；
> 歡迎以 issue / PR 回饋。
>
> 觸發脈絡：#29（安心樂租網）有貢獻者表達認領意願（2026-08）。dx-roadmap 4-6
> 「多站點抽象」的既定原則是**由真的要加第二站時驅動**——現在觸發了，本文件盤點
> 「讓其他人一起貢獻新平台爬蟲」需要處理的事。

## 已經到位的資產

先盤點不用重做的部分——多數擴充點在架構上早已預留：

- **Spider contract 本來就是 vendor 中立的**：`RentalSpider` 抽象定義
  `default_start_list` / `default_parse_list` / `default_parse_detail` 三件套與
  `gen_*_request_args`；`GenericHouseItem` 是正規化 schema。新站＝實作這個
  contract，不必動框架。
- **出貨端天生多來源**：資料集的 `sources[]`、UI 資料列、編碼表結構都支援多
  vendor，出貨管線零改動。
- **fixture / 離線測試方法論已成文**：scrub 標準（值全換、白名單剪枝、
  「scrub 前後 parse 結果相同」自我驗證）見
  `scrapy-tw-rental-house/tests/fixtures/README.md`；離線 pytest 已上公開 CI。
  新 vendor 的測試有現成軌道可掛。
- **手動開發迴路**：`twrh` CLI（parse／list／detail／survey／probe）讓 parser
  開發不需要 DB 與正式管線（現為 591 專用，一般化列於下）。

## 缺口與處理順序

### P0 —— 接受認領之前（流程與治理）

| 事項 | 說明 |
|---|---|
| **資料源認領流程成文** | 提案 → **robots / 服務條款 / 個資界線查證** → 量級與格式 survey → 才進 parser 實作。查證結果記在 data-source issue 內。爬蟲禮貌為預設：速率保守、遵守站方限制；**風控相關量測數據不進公開 repo**（本專案既有慣例）。 |
| **enum 編碼值治理成文** | `enums.py` 的整數值直接出現在公開資料集中，規則是**只能新增、永不改值/重編**。新 vendor 需要新的物件型態、區域等值時，一律 append；shared 與 vendor-specific 的邊界見 P1 拆分。 |
| **dataset 側測試 A 層（純邏輯）** | deal 狀態機（`syncstateful`，docstring 已有 O/N/D 轉移表）、月報紅綠判定、progress 語意。共用地基開放給外部貢獻前的最低安全網，不需 DB。 |

### P1 —— 收 parser PR 之前（架構解耦，dx-roadmap 4-1／4-6）

| 事項 | 說明 |
|---|---|
| **vendor 解耦（4-6）** | `PersistQueue` 的 vendor 改由 spider class attribute 提供；pipeline 的 Vendor 查找與 `vendors` fixture 的擴充流程文件化。 |
| **enums 拆 shared vs vendor-specific（4-6）** | deal_status 等跨站共用；物件/建物型態等依站拆分。拆分時遵守上述編碼值治理。 |
| **enums / tw_regions 單一來源（4-1）** | 目前 package 與 django 兩份且已漂移；多 vendor 會放大成 N 份，先收斂。 |
| **dataset 側測試 B 層（queue 語意）** | persist queue 的認領／釋放／batch／seed 組合矩陣（CI 掛 Postgres）。它是歷史上 bug 密度最高的共用件，變成多人共用地基前需要安全網；也是 4-6 重構自身的安全網。 |
| **`twrh` CLI 一般化** | list／detail／survey／probe 加 vendor 維度——這是貢獻者「不碰 DB 開發 parser」的主迴路。 |
| **哨兵 per-vendor 化** | 填充率 baseline、分佈不變量 baseline 目前是 591 全國一份；survey → baseline 的產出軌道現成，需一般化為 per-vendor 檔並各自接 nightly／daily 檢查。 |

### P2 —— 規模化後補

- 「新增 vendor 指南」一頁式文件（contract、`GenericHouseItem` 欄位必／選填、
  enum 對映規則、fixture 標準、review 流程）。
- data-source issue 模板（把 P0 流程變成表單）。
- 發版節奏說明（parser 在 PyPI 套件內，外部貢獻者依賴維護者發版；
  期間可用 editable install 於 dataset 側驗證）。

## 營運政策層：591 特有的爬法怎麼分層（2026-09-05 補）

deals stage（#229）與前緣掃描（短命物件）上線後，cron 裡多了一批看似
「591 專用」的東西。實際拆開是三層，只有第一層真的綁站方，管理方式各異：

| 層 | 內容 | 現在住哪 | 多 vendor 時 |
|---|---|---|---|
| **站方特性** | 成交只在「已成交」列表、50 窗／30 步距、不信 `total_page`、detail 404 即成交、新刊登連續排在 list 最前 | package 的 `Rental591Spider`／DealMixin | 位置正確，不動；每個 vendor 自己的 spider 承擔 |
| **機制（通用）** | `seed_mode=new`、逐頁走到整頁已知即收單、queue 互斥、breaker、queuefinalize | `persist_queue`、detail spider、`devop/sweep.sh` | 任何「list 依刊登時間排序」的站都能用；目前只是被 `list591`／`detail591` 這幾個 spider 名綁死 |
| **營運政策（per-vendor）** | 要不要跑 deals、要不要前緣掃描、幾小時一次、幾頁、lookback 幾天、sweep 併發與延遲、預設 seed_mode | 散在 `sweep.sh` 預設值、`flow.py` STAGES、`devop/aws` 變數與排程三處 | **需要收成一份 vendor profile** |

**目標形狀：vendor profile ＋ capability flags，機制不分家。**

- 每個 vendor 一份 profile（資料而非程式碼，例如 `crawler/vendors/591.py`
  或 yaml），六到八個 key：list／detail／deal 三個 spider 名、
  `has_deals_stage`、`supports_frontier`、`frontier_pages`、`deal_lookback_days`、
  sweep 速率、預設 seed_mode。
- flow 的 STAGES 改成「stage × profile」：deals／sweep 這類 stage 由 profile
  的 flag 決定要不要跑。低對抗的政府站就是 `has_deals_stage=false、
  supports_frontier=false`，只跑日跑。
- `devop/sweep.sh` 目前等於第三套 bash 編排，與 architecture-roadmap 3-2
  「收斂編排」方向相反；D6 退役 go.sh／orchestrate.sh 時一併收成
  `flow.py sweep --vendor <v>`（list-frontier → detail-new → queuefinalize）。
- Terraform 排程改為對 vendor map `for_each`，一個 vendor 兩條排程
  （`twrh-<vendor>-daily`／`twrh-<vendor>-sweep`）；節奏本就因站而異，
  不該共用一組全域變數。
- 哨兵 per-vendor 化（P1 既有項）要把 09-05 新加的 list 完整度哨兵
  （`n_open_in_list`）一併算進去。

**已經以 vendor 為維度、多一站免費的**：`RequestTS` queue 與 queuefinalize
的 (vendor, type) 矩陣、`raws/<vendor>/` 日包、housekeep 的 S3 路徑。

**已知洞**：`sweep.sh` 的互斥判斷看當日所有 in_flight 列、未過濾 vendor——
多 vendor 後 B 站日跑會擋 A 站前緣掃描。單 vendor 無感；收進 flow 時加
vendor 條件。

**時機**：不提前抽象。2-1／4-6 由第二個 vendor 觸發（沒有第二個實作者時
介面是猜的）；profile 於 D6 收編排時順手做，因為那時本來就要重寫這些 bash。

## 候選站評估原則（草案）

- **優先低對抗性、格式穩定的來源**（如政府站）作為第二站試點——多站抽象第一次
  走通時，不要同時揹商業站的風控／法律課題。
- 商業站（如大型仲介平台）待第一個新站走通、且 robots／服務條款查證通過後再議。
- 每個新站的永久成本：parser 改版維護、per-vendor baseline 與 fixture、
  nightly 檢查。認領時一併確認維護意願。

## 與既有文件的關係

- dx-roadmap 4-1／4-6：本文件是其「被觸發後」的展開；實作項回寫 dx-roadmap。
- `docs/export-automation-plan.md`：出貨端已多來源相容，無需變動。
- `tests/fixtures/README.md`：fixture／scrub 標準的單一來源，本文件僅指路。

## 編修紀錄

- **2026-09-05** 補〈營運政策層〉：deals／前緣掃描進 cron 後，把「591 特有」
  拆成站方特性／通用機制／per-vendor 營運政策三層，明訂 vendor profile 形狀、
  sweep 併入 flow 的時點（D6）與 sweep 互斥未過濾 vendor 的已知洞。
- **2026-08-30** Claude 起草（觸發：#29 認領意願）。尚未 review，歡迎回饋。
