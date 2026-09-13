# Schema 下一版草案：內部契約 v2 與對外資料集 1.0

> 草案，2026-09-13 初稿、同日依維護者回覆修訂（版號定為 1.0、欄位生命週期宣告、重刊留下一版）。
> §4 記錄已拍板事項；未完成的實作前不動 `rental/contracts.py`、不動 export。

## 0. 專案排序與抓資料原則（2026-09-13 拍板，schema 的上位規則）

**基本排序**

1. 擴大資料面（更多欄位、更多 vendor、更長歷史）。
2. 確保資料正確性、**可預測度**（錯誤說明、schema version）、**穩定度**（不隨意刪欄位，也不隨意加還不確定的欄位）。
3. 常見的基礎清理，例如重複偵測。
4. 不做太深入的研究；要做，也只是為了給範例。

**抓資料原則：相信客觀事實，而非行銷版位。**

- 591 的價格區間（`min_monthly_price`）不採用：每次 sweep 本來就能回推價格變動，且價格區間容易被動手腳當行銷。
  同理，591 頁面自帶的價格變動歷史（`priceCache`）屬平台宣稱，只當內部對帳輔助，公開資料的價格變動由我們自己的逐日觀測產生。
- 地址一定是模糊的（避免讓人知道哪裡有空屋、被查稅）：巷弄以下、門牌、社區名稱不落地；模糊座標維持現行精度。

**由原則推出的 schema 紀律**

| 紀律 | 內容 |
|---|---|
| 只增不改 | 新欄位 nullable append；改語意＝新欄位＋舊欄位標 deprecated；enum 值只 append、永不重編。 |
| 廢欄不刪 | 標 deprecated 的欄位繼續存在、值恆 NULL／`-`，至少跨一個公開版本後才移除，移除日期寫在文件。 |
| 先確定再進契約 | 新欄位先在 raw 與 parsed 分區觀察填充率與穩定度一個月（哨兵 baseline），再進公開版。 |
| 版本可見 | 每個分區檔帶 `*_version`；每個公開 zip 帶 `_meta.json`（schema 版本、產生時間、parser 版本、列數、已知問題連結）。 |
| 欄位生命週期 | 每個公開欄位標其中一個狀態：**實驗中**（新加入，語意或填充率可能調整，至少一個版本後才升穩定）→ **穩定** → **即將 deprecated**（預告版本與日期，值照出）→ **deprecated**（保留欄位、值恆 `-`）→ 移除（至少隔一個版本）。狀態寫在資料集文件的欄位表與 `_meta.json`。 |
| 錯誤說明 | 已知資料錯誤寫進 `ui-next` 的 quality-issues 與 `_meta.json`，標明受影響期間與欄位，不悄悄修。 |
| vendor 中立 | 共同表只放跨站可比的客觀事實欄；站方獨有欄進 `vendor_extra` JSON（內部）與 per-vendor 對照表（文件），不進共同 CSV 欄。政策型資料源走平行 pipeline（multi-vendor-plan 方案 B），不併入本表。 |

## 1. 現況問題（2026-09-13 盤點，1.0 要一併說明或修正）

| # | 問題 | 影響 | 處置 |
|---|---|---|---|
| P1 | list 頁 tag 被轉成 `facilities` 字典，pipeline 每個 list 日蓋掉 House／HouseTS 的 detail 版（本機 OPENED 72k 戶：tag 版 60,063、detail 版 11,171） | 公開 Raw 月包的「提供家具_*」自 2026-03 起約八成戶全 False | 內部：list item 不再產 `facilities`，tag 另立 `tags`；DB 現值由 raw 日包重放修復。公開：1.0 錯誤說明標受影響期間 |
| P2 | 2026 模板家具叫「桌椅」，export 查「桌子」「椅子」 | 兩欄 2026 起幾乎恆 False | 新增「提供家具_桌椅？」，「桌子」「椅子」標 deprecated |
| P3 | detail item 的 `rough_address` 恆 None，反向蓋掉 list 給的街道級地址 | 內部欄位不穩定（公開本就不出） | 內部：detail 不帶 `rough_address` key 即不覆寫；街道級以下不落地 |
| P4 | `living_functions`／`transportation`（含 public_bike）自 2021 起恆空，公開仍有 12 欄 | 12 欄恆 `-`，#235 第 1 點 | 1.0 標 deprecated，1.1 移除；周邊資訊改以 POI 距離另立（見 §2.3 候選） |
| P5 | `vendor_house_url` parsed 0%、House 現役戶 0 | 公開「物件網址」可能恆空（待查 202603 起月包） | 由 vendor profile 的 URL 樣板填，不靠頁面 |
| P6 | `min_monthly_price` 0%、原則上不採 | — | 標 deprecated，繼續寫 NULL |
| P7 | `imgs` 2.5.0 起 detail 全尺寸進 parsed；公開沒有任何照片欄 | — | 公開加「照片數」；URL 不公開（著作權） |
| P8 | 591 頁面有而我們沒收的客觀欄位（刊登日、瀏覽數、電費計價、服務費、最短租期、法定用途、建物面積、政策 tag、身份要求原文） | 資料面 | 進 parsed v2（§2.2），raw 日包自 9/4 起可重放回填；公開 1.0 以「實驗中」狀態出 |

## 2. 內部資料結構 v2（`rental/contracts.py`）

四張表不變：observation（原 list stub）、parsed、deal_event、snapshot。共同鍵不變：
`vendor`、`vendor_house_id`、`date`、`run`。所有新欄 nullable，append 在既有欄之後、`*_version` 之前。

### 2.1 observation v2（list stub，`stub_version` 1→2）

| 欄位 | 型別 | 說明 |
|---|---|---|
| （v1 全欄保留） | | `min_monthly_price`、`rough_address` 標 deprecated：前者恆 NULL；後者只留「路／街」級，巷弄以下截掉 |
| `tags` | JSON | vendor 原始 tag 字串陣列（591：可報稅、可入籍、租金補貼、屋主直租、社會住宅、影片賞屋…）。原樣保留、不解讀，解讀在 parsed／snapshot |
| `n_views` | I64 | list 頁瀏覽數（591 `view_count`）。客觀計數；每輪觀測一個值，時間序列自然形成 |
| `vendor_updated_hint` | STR | list 頁的相對更新字串原文（「3天前更新」）。只留原文供對帳，不解析成時間（相對字串天天漂） |
| `community_key` | STR | sha1(社區名稱)[:16]。只存雜湊：同社區比對用，名稱不落地（地址模糊原則） |

不放：`facilities`（list 端不再產生）、社區名稱原文、地址巷弄以下。

### 2.2 parsed v2（`parsed_version` 1→2）

| 欄位 | 型別 | 來源（591） | 說明 |
|---|---|---|---|
| （v1 全欄保留） | | | `min_monthly_price`、`living_functions`、`transportation` 標 deprecated 恆 NULL；`rough_address` 同 2.1 截到街道級；`vendor_house_url` 改由 profile 樣板填 |
| `tags` | JSON | nuxt `tags[].value` | 同 2.1，detail 版較完整 |
| `vendor_posted_at` | TS | `postTime`（「此房屋在8月14日發佈」→ 解析為日期） | 平台宣稱的刊登日。與我們的 `first_seen_at` 並列，不取代：前者是宣稱、後者是觀測 |
| `n_views` | I64 | `browse.pc + browse.mobile` | 總瀏覽數 |
| `views_detail` | JSON | `browse` | 分裝置明細，vendor 專屬形狀 |
| `electricity_fee_type` | I32 enum | `electric_fee_type` | 新 enum `ElectricityFeeType`：0 未填、1 台電計費、2 每度定價、3 含在租金、4 其他 |
| `electricity_fee_per_kwh` | F64 | 「每度6元」 | 只在 type=2 有值 |
| `water_fee_type` | I32 enum | `water_fee_type` | 新 enum `WaterFeeType`：0 未填、1 台水計費、2 定額、3 含在租金、4 其他 |
| `agent_fee_months` | F64 | `service_fee`（「半個月租金」→0.5） | 仲介服務費，以月租金倍數表示；面議／其他為 NULL |
| `min_lease_months` | I32 | 最短租期（「一年」→12） | |
| `tenant_requirements` | JSON | 身份要求原文（「學生、上班族、家庭」→ 陣列） | 保留原文陣列；既有 `has_tenant_restriction` 語意不變 |
| `legal_use` | I32 enum | 法定用途 | 新 enum `LegalUseType`：0 未填、1 住家用、2 商業用、3 工業用、4 其他 |
| `decoration_level` | I32 enum | `decorateDesc` | 新 enum `DecorationLevel`：0 未填、1 無裝潢、2 簡易裝潢、3 中等裝潢、4 高級裝潢 |
| `floor_ping_building` | F64 | 建物面積（不含公設） | 與既有 `floor_ping`（可使用面積）並列 |
| `contact_verified` | I32 enum | `certificateStatus` | 新 enum `ContactVerification`：0 未驗、1 審核中、2 已驗證、3 其他 |
| `tax_deductible` | BOOL | tag 可報稅 | 政策相關 tag 升為布林（拍板：升格，但 591 tag 變動快，`tags` 原文欄永遠保留） |
| `household_registration_ok` | BOOL | tag 可入籍 | 同上 |
| `accepts_rent_subsidy` | BOOL | tag 租金補貼 | 同上 |
| `is_social_housing` | BOOL | tag 社會住宅 | 同上 |
| `n_imgs` | I32 | `len(imgs)` | 公開用；`imgs` 本身仍只在內部 |
| `img_keys` | JSON | sha1(URL 去尺寸後綴)[:16] 陣列 | 同照片比對用（重刊偵測）；之後可換 pHash |
| `vendor_price_history` | JSON | `priceCache` | **內部對帳輔助**，不進公開、不進 snapshot 推導（原則：平台宣稱） |
| `vendor_extra` | JSON | 其餘站方獨有值（`socialHouse`、`isGoldAgent`、`rentNum`、`one_time_expenditure`、`endTime`…） | 逃生口：先收再決定要不要升格；升格＝新欄位，不改這裡 |

不放：地址巷弄以下、社區名稱原文、標題、描述全文、電話（描述與標題留在 raw 日包，需要時走 rerun）。

### 2.3 候選（觀察一個月再決定是否進 v2）

- `nearby`（JSON）：591 周邊 POI 型別＋距離＋座標（公車、學校、商圈…）。平台由座標算出，屬客觀；但語意與舊「附近有_*」（房東勾選）不同，不能拿來復活舊欄。替代想法：由我們的模糊座標＋政府開放圖資自己算「最近捷運站距離」等，vendor 無關，更符合原則，但受座標精度限制。
- `agent_n_listings`（仲介同時刊登數，`rentNum`）：抽樣 18 頁皆 0，填充率待驗。
- `house_age`／`direction`：591 有欄但房東不填（0/18），暫不收。

### 2.4 deal_event（不變，`event_version` 1）

### 2.5 snapshot v2（`snapshot_version` 1→2）

parsed v2 全欄＋既有 carry 欄，另加**由我們自己的觀測推導**的欄（第 3 點「基礎清理」的落點）：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `price_history` | JSON | `[{date, monthly_price}]`，只在價格改變時 append，來源＝每日 observation／parsed。客觀版價格變動，與 `vendor_price_history` 分開 |
| `n_price_changes` | I32 | `len(price_history) - 1` |
| `first_monthly_price` | I64 | 首見價 |
| `days_listed` | I32 | 首見到今日（或關閉／成交日）的天數，由 `first_seen_at` 推導；與 vendor 的 `n_day_deal` 並列 |
| `dup_key` | STR | 重複物件群組鍵＝sha1(vendor 中立欄：top_region、sub_region、property_type、building_type、floor、total_floor、floor_ping 取一位小數、apt_feature_code、rough_lat／rough_lng 取四位)[:16]。0.3 dedup 的「全欄相同」改為可重現的顯式鍵 |
| `relist_of` | STR | 同 `dup_key` 且（同 `author_key` 或 `img_keys` 有交集）的前一戶 `vendor_house_id`；只指前一戶，鏈由讀取端展開。**內部先算、公開留 1.1**（拍板）：重刊偵測演算法先在 snapshot 上跑並量誤判率，見 §2.7 |

### 2.6 pipeline 與寫入端連動（寫入路徑變更，各自單獨一晚上線）

1. list item 停產 `facilities`；`can_cook`／`allow_pet` 只在 tag 明示時設 True、不設 False（現行即如此）。
2. detail item 不帶 `rough_address` key（parser 目前本就不抓），避免 None 覆寫。
3. `vendor_house_url` 由 vendor profile 樣板生成（`https://rent.591.com.tw/{id}`）。
4. package 端：parser 補 §2.2 欄位到 raw dict，`GenericHouseItem` 加對應 Field（發版 2.6.0）；`twrh survey` 的填充率報告與 baseline 跟著加欄。
5. DB 側（雙軌期仍是真相）：`House`／`HouseTS` 加同名欄（migration）；S4／S3 切換後由 snapshot 接手。
6. 回填：raw 日包自 2026-09-04 起 `rerun_from_raws --parquet-dir` 重放產 parsed v2 分區；DB 的 facilities 現值以 `rerun --commit` 修復。9/4 之前無 raw，新欄位恆 NULL。

### 2.7 重複與重刊偵測演算法（1.0 前先做的工作項）

拍板：重刊公開欄留 1.1，但演算法現在就開始做；公開永遠維持兩版（原始＋去重複）。

- **重複（同一時點多筆刊登同一物件）**：`dup_key` 顯式鍵取代 0.3 的「全欄相同」。先量：同 `dup_key` 的群組大小分布、群組內價格與刊登者是否一致、跨 vendor 是否可比（鍵不含 vendor）。門檻：群組內 monthly_price 相同比率、`author_key` 相同比率各報一個數。
- **重刊（同一物件跨時間反覆上架）**：候選規則＝同 `dup_key` ＋（同 `author_key` 或 `img_keys` 交集≥1）＋前一戶已關閉或成交。量：重刊率（分母＝當月新戶）、重刊間隔分布、與 9/6 手工樣本 74% 的差距。照片雜湊先用 URL 去尺寸後綴的 sha1，之後再評估 pHash（要下載縮圖）。
- **輸出**：先只在 snapshot 內部欄與 quality manifest 報數，跑滿一個月、誤判率可解釋後，1.1 公開 `疑似重刊自`。
- **不做**：機器學習判重；語意仍是可列舉、可重現的規則（0.3 的精神）。

## 3. 對外資料集 1.0

### 3.1 定位

- 版號 1.0（拍板）：0.x 為 2018–2026 的演進期，1.0 起適用 §0 的生命週期宣告與 `_meta.json`。
- 沿用 0.3 的三份：Raw 月包（一戶一列、House 現況）、Deduplicated（月／季／年）、JSON Raw。
- 檔名與 URL 不變（`ui-next/scripts/check-urls.mjs` 保留清單）；zip 內新增 `_meta.json`。
- 跨 vendor：共同欄位表即 1.0 的全部欄位；每個 vendor 一節「原始資料與資料集欄位對照表」（0.3 已有此結構）。政策型資料源另出資料集，不併表。
- 1.0 **不移除任何欄位**；標 deprecated 的欄位值恆 `-`，於 1.1 移除，移除日期在 1.0 文件預告。
- 欄位狀態：0.3 既有且有值的欄位＝穩定；§3.3 新增欄位全部＝**實驗中**（1.1 視填充率與穩定度升穩定或調整）；§3.4＝deprecated。

### 3.2 `_meta.json`（可預測度）

```json
{
  "dataset_version": "1.0",
  "kind": "raw",
  "period": "2026-10",
  "generated_at": "2026-11-01T07:00:00+08:00",
  "vendors": {"591 租屋網": {"parser_version": "2.6.0", "rows": 123456}},
  "rows": 123456,
  "schema_url": "https://rentalhouse.g0v.ddio.io/about-data-set/1.0",
  "codebook_url": "https://rentalhouse.g0v.ddio.io/about-data-set/1.0#編碼表",
  "fields": {"刊登平台刊登時間": "experimental", "附近的公共自行車數": "deprecated", "月租金": "stable"},
  "known_issues": [
    {"id": "facilities-list-overwrite", "fields": ["提供家具_*"], "period": ["2026-03", "2026-10"],
     "url": "https://rentalhouse.g0v.ddio.io/quality-issues/facilities-list-overwrite"}
  ]
}
```

### 3.3 新增欄位（皆 nullable，缺值 `-`；1.0 全部標「實驗中」）

| 欄位名稱 | 來源欄 | 說明 |
|---|---|---|
| 刊登平台刊登時間 | `vendor_posted_at` | 平台宣稱的刊登日，與「物件首次發現時間」並列 |
| 瀏覽數 | `n_views` | 資料集最後一次更新時的平台瀏覽數 |
| 首見月租金 | `first_monthly_price` | 本資料集首次發現時的月租金 |
| 價格變動次數 | `n_price_changes` | 由本資料集逐日觀測計算，不採平台宣稱 |
| 在架天數 | `days_listed` | 首見到最後更新（或關閉／成交）的天數 |
| 重複物件群組編碼 | `dup_key` | 同編碼＝硬體與位置條件相同的物件；Deduplicated 資料集即依此合併 |
| 照片數 | `n_imgs` | 不提供照片內容或網址 |
| 電費計價方式 | `electricity_fee_type` | 編碼表新增 |
| 每度電價 | `electricity_fee_per_kwh` | 僅「每度定價」有值 |
| 水費計價方式 | `water_fee_type` | 編碼表新增 |
| 仲介服務費（月數） | `agent_fee_months` | |
| 最短租期（月） | `min_lease_months` | |
| 身份要求 | `tenant_requirements` | 以 `|` 分隔的原文，例如 `學生|上班族|家庭`；「有身份限制？」語意不變 |
| 法定用途 | `legal_use` | 編碼表新增 |
| 裝潢程度 | `decoration_level` | 編碼表新增 |
| 建物面積 | `floor_ping_building` | 不含公設；「坪數」維持可使用面積 |
| 刊登者已驗證？ | `contact_verified` | 平台的身分／證照驗證狀態 |
| 可報稅？ | `tax_deductible` | 刊登者是否聲明可申報租金支出 |
| 可入籍？ | `household_registration_ok` | |
| 接受租金補貼？ | `accepts_rent_subsidy` | |
| 社會住宅？ | `is_social_housing` | |
| 提供家具_桌椅？ | `facilities['桌椅']` | 取代「桌子」「椅子」 |
| 平台標籤 | `tags` | 以 `|` 分隔的平台原始標籤，**永久保留**（拍板）：政策布林是它的解讀，平台改 tag 時原文欄先接住 |

### 3.4 標記 deprecated（保留欄位、值恆 `-`、1.1 移除）

拍板：腳踏車與交通類全部 deprecated。

- 附近有_學校？／公園？／百貨公司？／超商？／傳統市場？／夜市？／醫療機構？（7 欄，2021 起恆空）
- 附近的捷運站數／公車站數／火車站數／高鐵站數／公共自行車數（5 欄，2021 起恆空）
- 提供家具_桌子？／椅子？（2026 起失真，改出「桌椅」）

**即將 deprecated（1.0 預告、1.1 標 deprecated）**：無。若 1.0 期間發現新增實驗欄無法穩定，走這條路徑而非直接移除。

### 3.5 語意修正與錯誤說明（寫進 1.0 文件與 quality-issues）

| 項目 | 內容 |
|---|---|
| 提供家具_* | 2026-03 起至 1.0 生效前的 Raw 月包，約八成物件的家具欄因 list 頁覆寫而全為 F；Deduplicated 亦受影響。1.0 起由 detail 頁決定，list 頁不再寫入。 |
| 提供家具_桌子／椅子 | 2026 年起 591 合併為「桌椅」，兩欄失真，1.0 改出「桌椅」。 |
| 附近有_*／附近的_*站數 | 2021 年 591 改版後即無資料，一直為 `-`；1.0 標 deprecated。 |
| 物件網址 | 待查 2026 月包是否為空；1.0 起由平台網址樣板生成，保證有值。 |
| 出租所費天數 | 2026-09 起改由 591 成交列表取得（`deal591`），成交日為平台提供、非本資料集推估；之前的值為推估。 |
| 座標 | 明寫精度與「非物件所在地」；1.0 不改精度。 |

### 3.6 明確不加入（記錄決策）

| 項目 | 理由 |
|---|---|
| 價格區間、平台自帶價格歷史 | 行銷版位／平台宣稱；價格變動由本資料集觀測產生 |
| 地址（任何精度）、社區名稱 | 地址一定模糊 |
| 標題、說明全文 | 含電話、LINE、地址與行銷文字；0.3 曾預告加標題，1.0 正式收回（拍板） |
| 照片網址 | 著作權；只出「照片數」 |
| 平台周邊 POI 距離 | 語意與舊欄不同、且可由座標＋開放圖資自算；列 1.1 候選 |

### 3.7 Deduplicated 資料集

維持兩版釋出（拍板）：Raw 與 Deduplicated 各自獨立、同版號。Deduplicated 改為以「重複物件群組編碼」合併（可重現），其餘欄位規則沿用 0.3（常見值、常見約略地點、物件最後更新時間）。新增欄位中屬布林與 enum 者取常見值，計數類（瀏覽數、價格變動次數、在架天數）取最大值。§2.7 的重刊鏈成熟後，1.1 再決定 Deduplicated 是否把重刊也併成一戶（那會改變「一列」的定義，需另行預告）。

## 4. 已拍板（2026-09-13）

1. 政策相關 tag 升為四個布林（可報稅、可入籍、接受租金補貼、社會住宅），**同時永久保留「平台標籤」原文欄**——591 的 tag 變動快，原文欄先接住、布林是解讀。
2. 重刊欄公開留 1.1；重刊偵測演算法現在開工（§2.7）；公開永遠維持 Raw＋Deduplicated 兩版。`dup_key`（重複物件群組編碼）進 1.0。
3. 版本資訊放哪：`_meta.json` 是 zip 內一個小檔，記 schema 版本、產生時間、parser 版本、列數、欄位狀態、已知問題。另一個選項是在 CSV 每一列多一欄「資料集版本」，好處是單獨一列被剪出去也知道版本，壞處是幾十萬列重複同一個值、且版本是檔案層級而非物件層級的屬性。決定：CSV 不加欄，JSON 匯出在頂層加 `dataset_version`，zip 一律附 `_meta.json`。
4. 標題與說明全文正式收回，不再預告。
5. 生效時點 2026-11-01（202610 月包），與 S3a 同版出貨；202609 仍為 0.3 並附錯誤說明。
6. 新 enum 值由 package `enums.py` 單一來源 append，初值照 §2.2。
7. 版號定為 **1.0**（非 0.4）；欄位生命週期宣告（實驗中／穩定／即將 deprecated／deprecated）自 1.0 起適用；腳踏車與交通類 12 欄 deprecated。

## 5. 施工順序建議（每晚一個寫入路徑變更）

1. export 立即修：家具「桌椅」對映、`vendor_house_url` 樣板、`_meta.json`（不改欄位、不需新版號，屬 0.3 內錯誤修正並記 quality-issue）。
2. list 停寫 `facilities`（twrh-dataset pipeline）。
3. package 2.6.0：parser 補 §2.2 欄位、`GenericHouseItem` 加 Field、survey／probe 加欄；`twrh-dataset` 升版。
4. contracts v2（四表 version +1）＋ DB migration 加欄；rerun 回填 9/4 起分區與 DB 現值。
5. snapshot 推導欄（`price_history`、`dup_key`、`relist_of`）＋ snapshotcheck 對應比對。
6. 1.0 文件（含欄位狀態表）、編碼表、quality-issues；與 S3a 同版出貨。
7. 平行：§2.7 重複／重刊演算法在 snapshot 上量測，報數進 quality manifest。

## 編修紀錄

- 2026-09-13 初稿：依當日拍板原則、facilities 覆寫根因、591 nuxt payload 欄位盤點、學界／媒體使用調查寫成。
- 2026-09-13 修訂：版號改 1.0；加欄位生命週期宣告；政策布林升格＋原文欄永留；重刊公開留 1.1、演算法先做（§2.7）；標題與說明收回；生效 2026-11-01；§4 改為已拍板紀錄。
