# 匯出發佈自動化計畫（export → 聚合 → S3 → UI）

> **草稿（2026-08-26 起），尚未實作，內容仍會變動。**所有 `檔案:行號` 與行為描述都經過實際查證。
> 目標：把「月底匯出 → 資料集上架 → 網站更新 → 通知」串成一條可重跑的流程，
> 品質有問題時停在人工敘事這一關，沒問題就直接出貨。

---

## 現況盤點（既有素材與缺口）

| 素材 | 位置 | 現況 |
|---|---|---|
| 月度匯出 | `django/manage.py export -p`（`export.py` `handle_periodic`） | ✅ 已自動：go.sh 最後一步，僅月底執行，產出上月 `[YYYYMM][CSV/JSON][Raw]` zip 到 `twrh-dataset/datas/` |
| 單月去重 | `csv-aggregator/dedup-single.sh` + `dedup-single.sql`（clickhouse local） | ✅ 存在，手動：Raw zip → `[YYYYMM][CSV][Deduplicated]` |
| 季/年聚合 | `csv-aggregator/merge-and-dedup.sh` + `merge-multiple.sql` | ✅ 存在，手動：多個月 Raw zip → `[YYYYQx/YYYY][CSV][Raw+Deduplicated]`。註：`export.py` 裡的季/年匯出**刻意註解掉**（DB 匯出太重），2023 起就是 clickhouse 路線，不要走回頭路 |
| 檔案驗證 | `csv-aggregator/check.sh` | ✅ 存在，手動：CSV/JSON 物件數比對 + **編碼表注入**（S3 上的 zip 內含 `編碼表/`，是這步放進去的） |
| S3 上傳 | — | ❌ **缺**：bucket 為 `twrh.s3.ap-northeast-3.amazonaws.com/<year>/<檔名>`，repo 內無任何上傳工具，歷來手動。本機亦無憑證（takeover 待決事項） |
| UI 資料列 | `ui-next/src/data/stats/<year>.json` | ❌ 手動維護：monthly/quarterly/annual 列（type、counts、sources、files、size、comment、`quality_issue`）。`download.ts` 由列組出 S3 URL，檔名格式即上表命名 |
| 品質事件 | `ui-next/src/data/quality-issues.ts` + blog data-issue 文章 | ❌ 手動：有資料品質事件時，人寫 blog 文 → 加 quality-issues 條目 → 受影響資料列標 `quality_issue: <id>` |
| 網站發佈 | `.github/workflows/ui-deploy.yml` | ✅ 已自動：push master 即建置 ui-next → gh-pages |
| 品質訊號 | `Stats`（每日 `n_expected/n_crawled/n_fail/n_list_fail`）、`RequestTS` 殘留、breaker CRITICAL log、`logs/fill-rates/`、`baselines/*.national.json` | ✅ 材料都在，缺「以月為單位」的彙整器。全國不變量 baseline（#219）本來就是為全量驗收準備的 |
| Slack | `settings_local.SLACK_WEBHOOK_URL`（statscheck 用）、nightly 的 `TWRH_SLACK_WEBHOOK` | ✅ 通道現成 |

**結論**：produce（export -p）與 deploy（ui-deploy.yml）兩端已自動，中段（聚合、驗證、上傳、UI 資料列、通知分岔）全是手動缺口。

---

## 目標流程

觸發：月底 go.sh 跑完之後，人工執行 `./publish.sh`（見〈開放問題〉3——維持
「爬蟲自動、出貨手動」的本機原則；流程本身全自動，人只按一次）。

```
publish.sh [YYYYMM]（預設上個月；冪等，可 --resume 從斷點續跑）
│
├─ 1. 聚合
│   ├─ dedup-single.sh → [YYYYMM][CSV][Deduplicated]
│   └─ 季末（3/6/9/12 月）加跑 merge-and-dedup.sh → [YYYYQx]；年末再跑 → [YYYY]
│
├─ 2. 驗證（quality gate，三層全過才算綠）
│   ├─ a. check.sh：CSV/JSON 物件數一致 + 編碼表注入
│   ├─ b. 全國不變量：clickhouse 對 Raw CSV 計算，比對 baselines/<最新>.national.json
│   │      （樓層中位數、型態占比、頂加率、填充率；容許差沿用 baseline 檔內定義）
│   └─ c. 爬蟲月報：Stats 彙整整月——缺爬日清單、日均 fail ratio、RequestTS 殘留、
│          breaker 事件（log 掃 error_rate_exceeded）→ 產出 <YYYYMM>.report.json
│
├─ 3. 上傳 S3：aws s3 cp 到 /<year>/（先 --dryrun 列清單，上傳後驗 size；冪等覆蓋）
│
├─ 4. 產 UI 資料列：counts 取自 export 的 stats json、size 取自 zip 實檔
│      → 寫入 ui-next/src/data/stats/<year>.json（monthly；季/年同理）
│
└─ 5. 分岔
    ├─ gate 全綠 → git commit（僅 stats json）→ push master → CI 自動發佈
    │      → Slack ✅「YYYYMM 已發佈」＋月報摘要（物件數、與上月差、S3 連結）
    └─ gate 有紅 → 不 push、不留半套發佈
           → Slack ⚠️ 附問題概述（缺哪些日、fail ratio、哪個不變量漂移多少）
           → 人工三件事：寫 data-issue blog 文、加 quality-issues.ts 條目、
             在資料列標 quality_issue: <id>
           → 補完後 ./publish.sh YYYYMM --resume 續跑 3–5（帶著標記出貨）
```

順序理由：聚合先於驗證（Deduplicated 也要驗）；上傳先於 UI 更新（UI 列一上線
連結就該是活的）；通知放最後、雙態都發（綠色也要留紀錄，不只報災）。

冪等設計：每步完成寫 marker 到 `datas/publish/<YYYYMM>.state.json`，
`--resume` 跳過已完成步驟；S3 覆蓋與 stats json 寫入都設計成重跑無害。

---

## 分階段實作（依賴順序）

| # | 項目 | 位置 | 成本 | 說明 |
|---|---|---|---|---|
| P1 | 月報產生器 + quality gate（2a–2c）| dataset（新 management command 或 script） | 中 | 唯一有新邏輯的一段。紅綠門檻值需拍板（見開放問題 4） |
| P2 | 聚合自動化：包 dedup-single / merge-and-dedup 的呼叫與檔名推導 | dataset `publish.sh` | 小 | 既有腳本已可用，只是串起來；季/年判斷跟著月份走 |
| P3 | S3 上傳 | `publish.sh` | 小 | 阻塞在憑證（開放問題 1）。建議專用 IAM user，權限僅 `s3:PutObject` 於 `<bucket>/<year>/*` |
| P4 | UI 資料列產生器 + commit/push + Slack 雙態通知 | `publish.sh` + 小工具 | 中 | stats json 為機器可寫的最小 diff；commit 訊息固定格式。quality_issue 標記**永遠人工** |
| P5 | 演練：用 datas/ 既有的 202510 歷史 zip 走一遍 dry-run（S3 用 --dryrun、push 用分支） | — | 小 | 全流程驗收；順便補 `csv-aggregator/README.md` |

註：**2026-08 會是第一個實戰月**，而它天生是「有問題」的月份（8/26 才接手爬，
整月缺 25 天）——第一次出貨必然走紅色分支，正好完整演練「Slack 概述 → 人寫文 →
--resume 出貨」這條路，敘事可類比 `beta-2025` 條目。

---

## 建議不做

| 項目 | 理由 |
|---|---|
| 把季/年匯出加回 `export.py` | 2023 已拍板 clickhouse 聚合路線；DB 全量匯出在爬蟲主機上太重，且月 zip 聚合天然可重跑 |
| 自動產生 data-issue 文章 | 品質敘事需要人的判斷與擔保——這正是紅色分支存在的目的。自動化只負責把「概述素材」送到人面前 |
| 紅燈時「先發佈、之後補標」 | 資料一上 S3 就會被下載；gate 紅就是不出貨，補完敘事帶著標記一起出 |
| 月中增量發佈 | 資料集以月為單位是對使用者的承諾，破壞它會讓下游 dedup 邏輯全部重寫 |
| publish 排 cron | 本機「不排 cron、出貨手動觸發」原則（takeover 拍板）；轉正式環境後再議 |

---

## 開放問題（需要拍板才能動工）

1. **S3 憑證進本機？** ✅ 拍板（2026-08-30）：用既有本機 `twrh` profile 上傳，
   不另開 user；權限不足時再對該 user 補 `s3:PutObject` 限定 `/<year>/*`。
2. **UI 更新直接 commit master，還是走 PR？** ✅ 拍板（2026-08-30）：採折衷——
   綠色分支直 push、紅色分支（帶 quality_issue 的）走 PR 讓人看一眼。
3. **觸發方式**：go.sh 月底自動接著跑 publish，還是永遠人工？
   建議：go.sh 月底時只在 Slack 提示「可以出貨了」，publish 由人執行——
   外部效應（S3、網站）留一個人類確認點，成本只是每月按一次。
4. **月報紅綠門檻** ✅ 拍板（2026-08-30）：單日 fail ratio > 10% → 該日 fail；
   當月有任一 fail 日（含缺爬日，即該日無 Stats 列）→ 紅。
   **分佈不變量永遠 advisory、不決定紅綠**——市場有季節性，跨月比對只進報告
   與敘事。baseline 選擇順位：前一次成功的**同期月** → 前一次成功月 →
   committed `baselines/national.json`；前兩者需歷史累積（2025 無資料），
   現階段一律落在 national.json，同期比對待資料齊備後生效。
5. **JSON 格式 zip 是否同步上傳**：`datas/` 有 `[YYYYMM][JSON][Raw]`，
   UI 的 files 欄也支援 json 列——假設是要的，P3 一併處理。

---

## 編修紀錄

- **2026-08-26** 建立。盤點 export -p／csv-aggregator／ui-next stats 資料流，
  定義 publish.sh 五步流程與紅綠分岔，列五個開放問題。
- **2026-08-30（二補）** **P2–P5 完成**：`twrh-dataset/publish.sh`（五步編排，
  紅綠分岔、state marker 冪等、--resume/--dry-run/--quality-issue）＋
  `tools/publish_ui_stats.py`（UI 資料列 upsert；size_byte＝解壓後資料檔，
  以 202510 歷史列驗證 diff 為零）。P5 演練以 202510 zip 走完 dry-run 全程
  （紅停敘事關卡→resume→S3 dryrun→UI→would-open-PR）。兩個機械修正：
  (a) check.sh 需先於 dedup-single 跑（注入編碼表），順序改為「驗 raw→聚合→
  驗 dedup」；(b) check.sh 必須在 csv-aggregator 自己的目錄執行（其清理是
  cwd 相對的 rm -rf）。distcheck 另落每日不變量 history（baseline 重製原料）。
- **2026-08-30** 開放問題 1、2、4 拍板（見各條 ✅）；**P1 完成**：
  `django/manage.py monthreport`（crawlerrequest app）——逐日 Stats 彙整、
  缺爬日/fail 日判定、RequestTS 殘留、breaker log 掃描（best effort）、
  分佈不變量 advisory 比對（與 distcheck 同一套 compare_invariants），產出
  `datas/publish/<YYYYMM>.report.json`，exit 0=綠/2=紅。以 202608 實資料驗證：
  紅（缺爬日 25 天）、逐日數字與 statscheck 一致、不變量 advisory 全過。
  2026-08 出貨走紅色分支＝首次實戰演練（聚合/上傳/UI 列先手動，P2–P4 後補）。
