# Schema 下一版草案：內部契約 v2 與對外資料集 0.4

> 草案，2026-09-13。依維護者當日拍板的專案排序與抓資料原則寫成；
> 每一節末尾列「待拍板」。未拍板前不動 `rental/contracts.py`、不動 export。

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
| 錯誤說明 | 已知資料錯誤寫進 `ui-next` 的 quality-issues 與 `_meta.json`，標明受影響期間與欄位，不悄悄修。 |
| vendor 中立 | 共同表只放跨站可比的客觀事實欄；站方獨有欄進 `vendor_extra` JSON（內部）與 per-vendor 對照表（文件），不進共同 CSV 欄。政策型資料源走平行 pipeline（multi-vendor-plan 方案 B），不併入本表。 |

## 1. 現況問題（2026-09-13 盤點，0.4 要一併說明或修正）

| # | 問題 | 影響 | 處置 |
|---|---|---|---|
| P1 | list 頁 tag 被轉成 `facilities` 字典，pipeline 每個 list 日蓋掉 House／HouseTS 的 detail 版（本機 OPENED 72k 戶：tag 版 60,063、detail 版 11,171） | 公開 Raw 月包的「提供家具_*」自 2026-03 起約八成戶全 False | 內部：list item 不再產 `facilities`，tag 另立 `tags`；DB 現值由 raw 日包重放修復。公開：0.4 錯誤說明標受影響期間 |
| P2 | 2026 模板家具叫「桌椅」，export 查「桌子」「椅子」 | 兩欄 2026 起幾乎恆 False | 新增「提供家具_桌椅？」，「桌子」「椅子」標 deprecated |
| P3 | detail item 的 `rough_address` 恆 None，反向蓋掉 list 給的街道級地址 | 內部欄位不穩定（公開本就不出） | 內部：detail 不帶 `rough_address` key 即不覆寫；街道級以下不落地 |
| P4 | `living_functions`／`transportation`（含 public_bike）自 2021 起恆空，公開仍有 12 欄 | 12 欄恆 `-`，#235 第 1 點 | 0.4 標 deprecated，0.5 移除；周邊資訊改以 POI 距離另立（見 §2.3 候選） |
| P5 | `vendor_house_url` parsed 0%、House 現役戶 0 | 公開「物件網址」可能恆空（待查 202603 起月包） | 由 vendor profile 的 URL 樣板填，不靠頁面 |
| P6 | `min_monthly_price` 0%、原則上不採 | — | 標 deprecated，繼續寫 NULL |
| P7 | `imgs` 2.5.0 起 detail 全尺寸進 parsed；公開沒有任何照片欄 | — | 公開加「照片數」；URL 不公開（著作權） |
| P8 | 591 頁面有而我們沒收的客觀欄位（刊登日、瀏覽數、電費計價、服務費、最短租期、法定用途、建物面積、政策 tag、身份要求原文） | 資料面 | 進 parsed v2（§2.2），raw 日包自 9/4 起可重放回填 |

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
| `tax_deductible` | BOOL | tag 可報稅 | 政策相關 tag 升為布林（語意穩定、591 tag id 固定） |
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
| `relist_of` | STR | 同 `dup_key` 且（同 `author_key` 或 `img_keys` 有交集）的前一戶 `vendor_house_id`；只指前一戶，鏈由讀取端展開。重刊偵測從分析層升為基礎清理欄 |

### 2.6 pipeline 與寫入端連動（寫入路徑變更，各自單獨一晚上線）

1. list item 停產 `facilities`；`can_cook`／`allow_pet` 只在 tag 明示時設 True、不設 False（現行即如此）。
2. detail item 不帶 `rough_address` key（parser 目前本就不抓），避免 None 覆寫。
3. `vendor_house_url` 由 vendor profile 樣板生成（`https://rent.591.com.tw/{id}`）。
4. package 端：parser 補 §2.2 欄位到 raw dict，`GenericHouseItem` 加對應 Field（發版 2.6.0）；`twrh survey` 的填充率報告與 baseline 跟著加欄。
5. DB 側（雙軌期仍是真相）：`House`／`HouseTS` 加同名欄（migration）；S4／S3 切換後由 snapshot 接手。
6. 回填：raw 日包自 2026-09-04 起 `rerun_from_raws --parquet-dir` 重放產 parsed v2 分區；DB 的 facilities 現值以 `rerun --commit` 修復。9/4 之前無 raw，新欄位恆 NULL。

## 3. 對外資料集 0.4

### 3.1 定位

- 沿用 0.3 的三份：Raw 月包（一戶一列、House 現況）、Deduplicated（月／季／年）、JSON Raw。
- 檔名與 URL 不變（`ui-next/scripts/check-urls.mjs` 保留清單）；zip 內新增 `_meta.json`。
- 跨 vendor：共同欄位表即 0.4 的全部欄位；每個 vendor 一節「原始資料與資料集欄位對照表」（0.3 已有此結構）。政策型資料源另出資料集，不併表。
- 0.4 **不移除任何欄位**；標 deprecated 的欄位值恆 `-`，於 0.5 移除，移除日期在 0.4 文件預告。

### 3.2 `_meta.json`（可預測度）

```json
{
  "dataset_version": "0.4",
  "kind": "raw",
  "period": "2026-10",
  "generated_at": "2026-11-01T07:00:00+08:00",
  "vendors": {"591 租屋網": {"parser_version": "2.6.0", "rows": 123456}},
  "rows": 123456,
  "schema_url": "https://rentalhouse.g0v.ddio.io/about-data-set/0.4",
  "codebook_url": "https://rentalhouse.g0v.ddio.io/about-data-set/0.4#編碼表",
  "known_issues": [
    {"id": "facilities-list-overwrite", "fields": ["提供家具_*"], "period": ["2026-03", "2026-10"],
     "url": "https://rentalhouse.g0v.ddio.io/quality-issues/facilities-list-overwrite"}
  ]
}
```

### 3.3 新增欄位（皆 nullable，缺值 `-`）

| 欄位名稱 | 來源欄 | 說明 |
|---|---|---|
| 刊登平台刊登時間 | `vendor_posted_at` | 平台宣稱的刊登日，與「物件首次發現時間」並列 |
| 瀏覽數 | `n_views` | 資料集最後一次更新時的平台瀏覽數 |
| 首見月租金 | `first_monthly_price` | 本資料集首次發現時的月租金 |
| 價格變動次數 | `n_price_changes` | 由本資料集逐日觀測計算，不採平台宣稱 |
| 在架天數 | `days_listed` | 首見到最後更新（或關閉／成交）的天數 |
| 重複物件群組編碼 | `dup_key` | 同編碼＝硬體與位置條件相同的物件；Deduplicated 資料集即依此合併 |
| 疑似重刊自 | `relist_of` | 前一次刊登的物件編號（同群組且同刊登者或同照片） |
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
| 平台標籤 | `tags` | 以 `|` 分隔的平台原始標籤，供對照；語意依平台而異 |

### 3.4 標記 deprecated（保留欄位、值恆 `-`、0.5 移除）

附近有_學校？／公園？／百貨公司？／超商？／傳統市場？／夜市？／醫療機構？；附近的捷運站數／公車站數／火車站數／高鐵站數／公共自行車數；提供家具_桌子？／椅子？。

### 3.5 語意修正與錯誤說明（寫進 0.4 文件與 quality-issues）

| 項目 | 內容 |
|---|---|
| 提供家具_* | 2026-03 起至 0.4 生效前的 Raw 月包，約八成物件的家具欄因 list 頁覆寫而全為 F；Deduplicated 亦受影響。0.4 起由 detail 頁決定，list 頁不再寫入。 |
| 提供家具_桌子／椅子 | 2026 年起 591 合併為「桌椅」，兩欄失真，0.4 改出「桌椅」。 |
| 附近有_*／附近的_*站數 | 2021 年 591 改版後即無資料，一直為 `-`；0.4 標 deprecated。 |
| 物件網址 | 待查 2026 月包是否為空；0.4 起由平台網址樣板生成，保證有值。 |
| 出租所費天數 | 2026-09 起改由 591 成交列表取得（`deal591`），成交日為平台提供、非本資料集推估；之前的值為推估。 |
| 座標 | 明寫精度與「非物件所在地」；0.4 不改精度。 |

### 3.6 明確不加入（記錄決策）

| 項目 | 理由 |
|---|---|
| 價格區間、平台自帶價格歷史 | 行銷版位／平台宣稱；價格變動由本資料集觀測產生 |
| 地址（任何精度）、社區名稱 | 地址一定模糊 |
| 標題、說明全文 | 含電話、LINE、地址與行銷文字；0.3 曾預告加標題，0.4 收回此預告 |
| 照片網址 | 著作權；只出「照片數」 |
| 平台周邊 POI 距離 | 語意與舊欄不同、且可由座標＋開放圖資自算；列 0.5 候選 |

### 3.7 Deduplicated 資料集

改為以「重複物件群組編碼」合併（可重現），其餘欄位規則沿用 0.3（常見值、常見約略地點、物件最後更新時間）。新增欄位中屬布林與 enum 者取常見值，計數類（瀏覽數、價格變動次數、在架天數）取最大值。

## 4. 待拍板

1. 政策相關 tag 升為四個布林（可報稅、可入籍、接受租金補貼、社會住宅）還是只出「平台標籤」原文？草案建議升格：語意穩定、跨站可對映、是租屋黑市研究的核心欄。
2. `relist_of`（重刊）進 0.4 還是先只出 `dup_key`、重刊留 0.5？草案建議一起進：規則簡單且可重現，但需先在 snapshot 上跑一個月看誤判率。
3. `_meta.json` 之外，CSV 本體要不要加常數欄「資料集版本」？草案建議不加（每列重複），JSON 版加頂層欄位。
4. 標題：0.3 預告過要加，0.4 正式收回，是否同意。
5. 0.4 生效時點：建議與 S3a（export 改讀 snapshot）同一版出貨，避免 export 改兩次；即最早 2026-11-01 出 202610 月包。過渡期 202609 仍為 0.3 並附錯誤說明。
6. enum 新值（電費／水費計價、法定用途、裝潢程度、驗證狀態）的編碼由 package `enums.py` 單一來源 append，是否同意上列初值。

## 5. 施工順序建議（每晚一個寫入路徑變更）

1. export 立即修：家具「桌椅」對映、`vendor_house_url` 樣板、`_meta.json`（不改欄位、不需新版號，屬 0.3 內錯誤修正並記 quality-issue）。
2. list 停寫 `facilities`（twrh-dataset pipeline）。
3. package 2.6.0：parser 補 §2.2 欄位、`GenericHouseItem` 加 Field、survey／probe 加欄；`twrh-dataset` 升版。
4. contracts v2（四表 version +1）＋ DB migration 加欄；rerun 回填 9/4 起分區與 DB 現值。
5. snapshot 推導欄（`price_history`、`dup_key`、`relist_of`）＋ snapshotcheck 對應比對。
6. 0.4 文件、編碼表、quality-issues；與 S3a 同版出貨。

## 編修紀錄

- 2026-09-13 初稿：依當日拍板原則、facilities 覆寫根因、591 nuxt payload 欄位盤點、學界／媒體使用調查寫成。
