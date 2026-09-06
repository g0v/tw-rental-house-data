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
| **選站評分式與認領表單欄位**（2026-09-07 補，源自 `vendor-landscape-2026-09.md` §4） | 提案者自算：`邊際價值 = 母體互補性 × 生命週期可觀測性 × 欄位獨特性 × 覆蓋廣度`、`永久成本 = parser 改版頻率 + per-vendor baseline/fixture + 法律與 ToS 風險`、`優先度 = 邊際價值 / 永久成本 × 認領可信度`。**覆蓋廣度**（一個 parser 覆蓋幾個縣市／學校／機關）是差距可達兩個數量級的變數；認領表單必填「**目的分類**」：架構驗證／資料價值／政策資料，三者驗收標準不同。 |
| **排除清單成文** | FB 社團／Dcard／PTT／LINE 群：個資與 ToS 紅線、無穩定 schema，**不接受提案**。品牌公寓與包租代管業者官網：站點分散、生命週期短，成本效益最差，延後。 |
| **dataset 側測試 A 層（純邏輯）** | deal 狀態機（`syncstateful`，docstring 已有 O/N/D 轉移表）、月報紅綠判定、progress 語意。共用地基開放給外部貢獻前的最低安全網，不需 DB。 |

### P1 —— 收 parser PR 之前（架構解耦，dx-roadmap 4-1／4-6）

| 事項 | 說明 |
|---|---|
| **vendor 解耦（4-6）** | `PersistQueue` 的 vendor 改由 spider class attribute 提供；pipeline 的 Vendor 查找與 `vendors` fixture 的擴充流程文件化。 |
| **enums 拆 shared vs vendor-specific（4-6）** | deal_status 等跨站共用；物件/建物型態等依站拆分。拆分時遵守上述編碼值治理。 |
| **enums / tw_regions 單一來源（4-1）** | 目前 package 與 django 兩份且已漂移；多 vendor 會放大成 N 份，先收斂。 |
| **dataset 側測試 B 層（queue 語意）** | persist queue 的認領／釋放／batch／seed 組合矩陣（CI 掛 Postgres）。它是歷史上 bug 密度最高的共用件，變成多人共用地基前需要安全網；也是 4-6 重構自身的安全網。 |
| **`twrh` CLI 一般化** | list／detail／survey／probe 加 vendor 維度——這是貢獻者「不碰 DB 開發 parser」的主迴路。 |
| **survey 報告標準格式**（2026-09-07 補） | 除物件總數、日新增、欄位覆蓋率、JSON API 或 HTML、是否需登入、robots／ToS、個資邊界之外，加上 591 這一週教的三項：(a) **list 排序鍵是否為刊登時間**（決定前緣掃描能不能用，profile 的 `supports_frontier`）；(b) **下架與成交訊號在哪裡**（591 改版後成交只在另一個列表、detail 直接 404——#229 就是 survey 沒問才事後發現；profile 的 `has_deals_stage`）；(c) **重刊率**（同地址＋坪＋型態＋樓層比對；9/6 凌晨樣本 74% 為重刊，不先量會把量級高估一倍）。 |
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

## 政策資料源的 schema 策略（開放，等 survey 再拍板）

`vendor-landscape-2026-09.md` §1.1 指出政策部門（社宅招租、包租代管）的基本
單位是「公告／戶別／抽籤梯次」的事件流，與 `GenericHouseItem` 的持續刊登
物件不同，並建議「方案 B：平行 pipeline、出貨端匯合」。

以 repo 現況修正其範圍：Phase 1＋3 落地後，**queue 與狀態機、raw 日包、
manifest 與斷言引擎、flow 的 stage 表、vendor profile 都是 vendor 中立的**，
政策站照用；真正會不同的只有兩層——parse 產出的 normalized 契約，與
snapshot 的生命週期語意。enum 不可逆的顧慮成立，但解法是既定的「shared
與 vendor-specific enum 拆開、只 append」：政策站的抽籤狀態放自己的 enum
檔、不碰 `deal_status`。

因此候選只有兩種形狀，**2026-09-07 拍板：先不決定，等實際看過站方資料
（survey）再定**；唯一先定的是「第一個政策站的 PR 不得隱性決定 schema」——
認領時要先出 survey 與契約草案，維護者拍板後才進 parser：

| 形狀 | 內容 | 代價 |
|---|---|---|
| 共用地基、分開契約 | 抓取／raw／manifest／flow 一套；normalized 契約與出貨表 per source（`parsed/<source>/`）；斷言檔 per source | 測試與哨兵仍一套；出貨端要多一種表 |
| 兩軌 | 政策站獨立 item schema 與 spider 基底，僅出貨端 `sources[]` 併呈 | 兩套測試軌道、兩套哨兵；共用地基零汙染 |

架構驗證（Vendor Protocol 2-1）由**與 591 同構的持續刊登站**承擔，政策站
不承擔——這點不待 survey，先定。

## 候選站評估原則（草案）

- **優先低對抗性、格式穩定的來源**（如政府站）作為第二站試點——多站抽象第一次
  走通時，不要同時揹商業站的風控／法律課題。
- 商業站（如大型仲介平台）待第一個新站走通、且 robots／服務條款查證通過後再議。
- **外部盤點的排序（2026-09-07，`vendor-landscape-2026-09.md` §5，未經 survey、
  應被量測推翻）**：(1) 教育部雲端租屋平臺——持續刊登型、一個 parser 覆蓋
  200+ 校、帶賃居評核欄位，同時承擔架構驗證與資料價值；(2) 臺北市安心樂租網
  （#29）——政策資料源、事件流、不承擔架構驗證；(3) 崔媽媽（fixture 蟹居網
  pk=3）——量小、優先談授權或匯出而非爬；(4) 包租代管與各縣市社宅——走
  資訊公開申請，不逐站爬；(5) 好房網（pk=2）——價值在交叉驗證（幽靈物件率、
  重刊率）而非新增物件，屬分析層、獨立立項不混進 vendor 擴充。樂屋網、
  我家網延後。
- 每個新站的永久成本：parser 改版維護、per-vendor baseline 與 fixture、
  nightly 檢查。認領時一併確認維護意願。

## 與既有文件的關係

- dx-roadmap 4-1／4-6：本文件是其「被觸發後」的展開；實作項回寫 dx-roadmap。
- `docs/export-automation-plan.md`：出貨端已多來源相容，無需變動。
- `tests/fixtures/README.md`：fixture／scrub 標準的單一來源，本文件僅指路。

## 編修紀錄

- **2026-09-07** 併入外部盤點 `vendor-landscape-2026-09.md`（Claude web 調查，
  未熟 repo；程式面以本文為準）：P0 加選站評分式／覆蓋廣度／目的分類／排除
  清單；P1 加 survey 標準格式（含 591 這週教的三項）；新增〈政策資料源的
  schema 策略〉——共用地基分開契約 vs 兩軌，**等 survey 看過站方資料再拍板**，
  先定「政策站 PR 不得隱性決定 schema、架構驗證交同構站」；候選站節補排序。
- **2026-09-05** 補〈營運政策層〉：deals／前緣掃描進 cron 後，把「591 特有」
  拆成站方特性／通用機制／per-vendor 營運政策三層，明訂 vendor profile 形狀、
  sweep 併入 flow 的時點（D6）與 sweep 互斥未過濾 vendor 的已知洞。
- **2026-08-30** Claude 起草（觸發：#29 認領意願）。尚未 review，歡迎回饋。
