# 月更自動化統計計畫（monthly insights）

> **狀態**：本文件由 Claude 起草（2026-09-02），**尚未經維護者完整 review**。
> 觸發脈絡：UI 改版完成後，希望每月資料更新時同步產出一組自動化統計，
> 讓資料集「不只可下載，還能直接看見市場」。本文盤點各界既有的租屋
> 分析方法，對映到本資料集可自動化的欄位，提出分期實作建議。

---

## 一、各界怎麼分析租屋資料（方法盤點）

### 政府部門

- **內政部不動產資訊平台**：以租賃實價登錄公布**各行政區租金四分位數**
  （P25／P50／P75），樣本數足夠的行政區再依**整層（戶）／獨立套房／
  分租套（雅）房**三類型態分列；樣本不足即不公布（min-samples 護欄）。
  這是台灣官方租金統計的基準格式。
- **主計總處 CPI 房租類指數**：以續租樣本為主的存量指數，變動極平滑、
  對市場轉折反應慢——這正是民間開價（asking rent）資料的互補空間。
- 北市主計處、各縣市住宅平台：租金指數與市場概況報告（年度／季度）。

### 國際租屋平台（方法論最成熟的參照）

- **Zillow ZORI**（repeat-rent index）：只比較**同一物件跨時間的價格差**
  再聚合，消除「這個月上架的房子跟上個月不一樣」的組成偏誤
  （composition bias）；水準值取 35–65 百分位均值、按住宅存量加權。
- **Apartment List**：same-unit repeat-transaction 成長率＋官方普查錨定
  水準；另編 **vacancy index**——用刊登生命週期量供需鬆緊。
  兩家共同點：**開價指數領先官方 CPI 租金約 6–12 個月**，是其存在價值。

### 媒體與學界

- **報導者〈小宅化〉專題（2024）**：**就是用本資料集**（2019–2023 約
  397 萬筆）做的——小宅（<20 坪整層）占比、平均坪數趨勢、每坪租金
  五年漲幅、型態占比消長、區域熱點成長倍數；清洗用 2σ 離群值排除。
  等於已經幫我們驗證過「這批欄位撐得起哪些敘事」。
- **學界（政大不動產研究中心等）**：hedonic（特徵價格）租金指數、
  空間迴歸；經典發現如「雅房／分租套房每坪租金反而**高於**整層住家
  6.5%／2.4%」的品質—單價倒掛現象——適合做成長期追蹤指標。
- **業界（房仲／投資）**：去化天數（time-on-market）、租金報酬率
  （需房價資料，跨資料集）。**housefeel.com.tw**：主力在房價側
  （實價登錄），租屋側是知識庫＋**租金負擔試算**（租金÷薪資）——
  負擔能力視角值得借鏡，行情統計則非其重心。

---

## 二、對映到本資料集：能自動月更的統計

原則：全部依 **city × 型態（property_type）** 分層、設 min-samples 門檻
（學內政部）、離群值截尾（P1–P99 或 2σ）。以下依實作難度與獨特性分組。

### A. 行情水準（內政部式，入門款）

| 指標 | 欄位 | 備註 |
|---|---|---|
| 每坪租金 P25/P50/P75 | monthly_price／floor_ping | 與內政部四分位數**直接可比對**（我們是開價、他們是成交價，價差本身就是內容） |
| 月租金／坪數中位數 | 同上 | |

### B. 趨勢指數（ZORI 式，本資料集的殺手級優勢）

| 指標 | 做法 | 備註 |
|---|---|---|
| **same-unit 開價變動指數** | 同一 vendor_house_id 跨月價格差聚合（35–65 百分位截尾） | 每日快照天生就是 repeat observation；**領先 CPI 房租**是對外的核心賣點 |
| 重新上架價差 | 物件下架後回列的價格變化 | L-C 的 returned 事件天生產出此資料 |

### C. 供需與流速（Apartment List vacancy 式，listing 生命週期獨有）

| 指標 | 欄位／事件 | 備註 |
|---|---|---|
| 新上架量／下架量／存量 | 每日 OPENED、狀態事件 | 市場溫度計 |
| 去化天數 P50 | 上架→下架天數 | **#229 語意：是「下架天數」非「成交天數」**，呈現時必須如實標註 |
| 長滯留物件占比 | 上架 >90 天仍 open | 供給黏著度 |

### D. 結構變化（報導者式）

小宅（<20 坪整層）占比、型態占比消長（整層／套房／雅房）、建物型態
（電梯大樓／公寓）占比、頂加（is_rooftop）占比——全部是現有欄位的
groupby，報導者已驗證敘事價值。

### E. 負擔與租屋條件（公民團體視角，少有人做、我們欄位齊全）

| 指標 | 欄位 | 備註 |
|---|---|---|
| 租金負擔比 | 中位數月租 ÷ 各縣市可支配所得（主計處，年更外部 join） | housefeel 試算器的統計版 |
| 限制條款統計 | 性別／身分限制、可養寵物、可開伙占比 | **資料集獨有的社會價值**：租屋歧視與條件的量化追蹤 |
| 品質—單價倒掛 | 雅房／套房 vs 整層每坪單價比 | 學界發現的長期追蹤版 |

---

## 三、實作形狀（與既有管線的接法）

- **產出**：export 階段多產一份 `[YYYYMM][Stats] insights.json`
  （或直接寫進 `ui-next/src/data/insights/<year>.json`），與現行
  stats json 同軌——publish.sh 第 4 步順手多寫一檔，UI build 時吃。
- **計算引擎**：對月 zip 的 CSV 用 clickhouse local 或 DuckDB 掃
  （不碰 DB → 與 publisher 雲化相容、任何人拿公開 zip 可重算＝
  **統計本身可驗證**，符合開放資料精神）。
- **UI**：download 頁或新 `/insights` 頁，Astro island＋輕量圖表；
  每月一篇自動產出的「本月市場速覽」區塊，人工敘事（blog）維持人寫。
- **護欄**：
  - min-samples（樣本不足的分層不出數字，學內政部）；
  - `is_synthesized` 列：水準統計可用（沿用值），**same-unit 變動指數
    必須排除**（合成列無新觀測）；
  - #229 語意標註進所有流速類指標的圖說；
  - 統計口徑版本化（口徑改了要能對舊月份重算，正好是月 zip 可重跑的
    天然優勢）。

### 分期建議

| 期 | 內容 | 依賴 |
|---|---|---|
| P1 | A 行情四分位數＋C 存量/流量＋D 結構占比 | 純 groupby，月 zip 即可算 |
| P2 | B same-unit 指數＋去化天數 | 需跨月串 house_id（拿歷月 zip 串或掃 DB） |
| P3 | E 負擔比＋限制條款專題頁 | 外部所得資料 join；適合搭一篇發布文 |

---

## 參考來源

- 內政部不動產資訊平台租金統計（[租金統計資訊](https://pip.moi.gov.tw/V3/E/SCRE0108.aspx)、[新聞稿](https://www.moi.gov.tw/)）
- [Zillow ZORI methodology](https://www.zillow.com/research/methodology-zori-repeat-rent-27092/)、[Apartment List rent estimate methodology](https://www.apartmentlist.com/research/rent-estimate-methodology)、[Apartment List vacancy index](https://www.apartmentlist.com/research/apartment-list-vacancy-index-methodology)
- [報導者：小宅化如何影響租屋市場（使用本資料集）](https://www.twreporter.org/a/data-reporter-era-of-small-sized-housing-unit-impact-on-rental-housing-market)
- 政大不動產研究中心：[租賃住宅市場租金指數建置](https://rer.nccu.edu.tw/article/detail/2502215240810)、[租金交易透明化實證](https://rer.nccu.edu.tw/article/detail/2502241156894)；[租屋市場之租金與住宅品質（品質—單價倒掛）](https://www.airitilibrary.com/Article/Detail/10181067-202209-202210040003-202210040003-317-339)
- [主計總處：CPI 房租之編製說明](https://www.stat.gov.tw/News_Content.aspx?n=2670&s=230873)
- [HouseFeel 房感](https://www.housefeel.com.tw/)（房價分析＋租金負擔試算）

## 編修紀錄

- **2026-09-02** Claude 起草（觸發：ddio 提議 UI 月更自動化統計）。
