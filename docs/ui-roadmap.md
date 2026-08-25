# UI 改版計畫（Nuxt 2 → Astro）

> 本計畫與爬蟲／資料管線的更新（`docs/dx-roadmap.md`）**沒有相依關係，分開處理、分開排程**。
> 兩邊唯一的接點是 `ui/assets/stats/*.json` 的手動維護流程，改版前後不變。
> 現況段落的檔案與行為都經過實際盤點（2026-08-25）；編修紀錄見文末。

---

## 已拍板的決策（2026-08-25）

| 決策 | 內容 | 理由 |
|---|---|---|
| 框架 | **Astro**（起步時為 v7）+ 靜態輸出 | 全站 95% 是純內容，僅三處需要 client JS（sticky TOC、Disqus、未來圖表）。Astro 預設零 JS，互動元件用 island 局部加載 |
| CSS | **Tailwind CSS v4**（`@tailwindcss/vite` plugin） | 需求「彈性但模組化」；現況已是 Tachyons 原子 CSS，心智模型近乎一比一遷移 |
| 元件層 | **Vue 3 SFC 為主**，`.astro` 只做頁面入口與 layout | 保住 HTML 可讀性與 highlight（不用 JSX 式的 `{rows.map(...)}` 寫迴圈）；未來互動元件同檔案加 `client:*` 就地升級 |
| 模板語言 | **不再使用 Pug**，一律 plain HTML 風格 | 全部頁面反正要重寫，Pug 在此自然退場 |
| 未來互動（統計圖表） | 先以 **Vue island**（`client:visible`）承接，**不**為此預先換 Nuxt | 圖表互動範圍是元件內部，正是 island 甜蜜點；升級 Nuxt 的訊號見〈何時該升級成 Nuxt〉 |
| 流量分析 | **Plausible 停用，改用 GoatCounter**（`ddio.goatcounter.com`，與 8h-probe 同一套） | 一行 `<script data-goatcounter=…>` embed，無 framework 整合依賴，個人專案集中在同一個 GoatCounter 帳號 |
| 留言系統 | **Disqus 退場，改用 [Cusdis](https://cusdis.com)（hosted 方案）**；舊 Disqus 留言不遷移 | 匿名留言不綁任何帳號（不限 GitHub）、無廣告無 cookie、embed 約 5KB，與換 GoatCounter 同方向。留言預設進審核，低流量站可負擔。風險：小型專案，hosted 服務若收掉，換家成本只是一段 script |
| Sentry | **移除，不帶到新站** | 靜態站的前端錯誤監控價值低，卻是 build 依賴與 CI secrets 裡最重的一塊；錯誤回報靠使用者留言/開票即可 |
| 視覺方向 | **資料新聞編輯室 × 磁磚綠**（2026-08-25 定案，mockup 見 design canvas「開租新站設計」）：編輯室版面（明體刊頭、「本期資料 No.」、資料品質備忘側欄、細線年份檔案庫）＋磁磚綠 `#2F7E68`／磨石子 `#E9E6DE`／鐵鏽紅 `#B5543B`（僅品質警示）／墨 `#22271F`；字型 Noto Serif TC（標題）＋ Noto Sans TC（內文）＋ IBM Plex Mono（數據） | 曾比較街屋鐵窗花方向——配色獲採用，但鐵窗花 pattern 與「一年一層樓」被否決（太俗）；綠色系同時延續現站識別 |

**Vue SFC 不加 `client:*` 指令時由 Astro 在 build 時渲染成純 HTML、不出貨任何 JS** —— 這是整個架構的核心心智規則，寫元件時唯一要記得的事。

---

## 現況盤點（改版要 cover 的全部範圍）

規模：8 個 page、8 個 component、2 個 layout，合計約 700 行 Vue（Pug 模板）。

| 區塊 | 現況 | 遷移後 |
|---|---|---|
| 部落格 | 19 篇 md（`content/blog/`），`@nuxt/content` 1.x；frontmatter：`title/author/created/cover/tags`；`<!--more-->` 當摘要分隔 | Content Collections + zod schema（frontmatter 打錯字改為 build error）；`<!--more-->` 需自寫小工具切摘要，或改用 frontmatter `description` |
| Download 頁 | `assets/stats/2018–2026.json`（**手動維護、直接 commit**，repo 內無產生器），build 時 import，`AnnualDownload`/`DownloadTable` 渲染，連結指向 S3（`libs/defs.js` 的 `S3_BASE`） | JSON 維護流程**完全不變**；頁面藉此機會重新設計（樣貌待定，見〈待拍板〉），仍是一般靜態網頁 |
| 關於資料集 | 0.0–0.3 四個版本頁，markdown **內嵌在 `.vue` 裡**用 `vue-markdown` 渲染 + DOM 時序 hack 產 TOC（#2/#212） | 抽成獨立 `.md` + 共用 layout；TOC 改用 Astro `render()` 回傳的 `headings`，該類 bug 在架構上消失；sticky TOC 用 CSS `position: sticky`，不需 JS |
| 樣式 | Tachyons + 少量 scoped SCSS；**`nuxt-buefy` 裝了但全站零使用**（殭屍依賴）；FontAwesome | Tailwind v4；Buefy/Tachyons 隨遷移丟棄；icon 需求盤點後可考慮换 inline SVG 減少一個字型依賴 |
| 整合 | Disqus、Plausible、Sentry、OG meta、schema.org microdata、google-site-verification | OG/schema.org/site-verification 照搬；Plausible 換 GoatCounter、Disqus 換 Cusdis、Sentry 移除（皆已拍板） |
| 部署 | `nuxt generate` → `peaceiris/actions-gh-pages` → gh-pages，CNAME `rentalhouse.g0v.ddio.io`；workflow 用 **Node 14**（`.nvmrc` 是 16，長期不一致） | `astro build` + 同一套 gh-pages action；Node 一次升到 Astro 要求的 LTS，`.nvmrc` 與 CI 對齊 |
| RSS / sitemap | **皆無** | 順手補：`@astrojs/rss` 與 `@astrojs/sitemap`（成本極小，blog 讀者受益） |

---

## URL 保留清單（改版驗收的硬條件）

blog 文章有外連與 OG 分享，以下路徑必須逐條保住（含結尾斜線行為，
Astro 預設 directory 輸出格式與現況 gh-pages 相同）：

- `/`、`/download`、`/blog`
- `/about-data-set` → 307/meta redirect 到 `/about-data-set/0.3`（現況行為）
- `/about-data-set/0.0`、`/0.1`、`/0.2`、`/0.3`
- `/blog/post/<slug>`，共 19 篇：
  `2019-anniversary`、`2020-09-automation-help-needed`、`2021-annual-data`、
  `2024-sep-return`、`2024-system-upgrading`、`2024-twrh-pipeline`、
  `2025-back-to-beta`、`2025-nov-release`、`2025-oct-release`、
  `clickhouse-local-aggregation`、`data-issue-2019-00`～`03`、
  `data-issue-2021-00`～`01`、`data-issue-2023-00`～`01`、`resurrection`
- `/blog/post`、`/blog/tag` → redirect 到 `/blog`（現況行為）
- `/blog/tag/<tag>`，現有 6 個 tag：`591租屋網`、`定期紀錄`、`封面圖片使用 AI 生成`、
  `技術文件`、`資料品質`、`關於`（中文 slug，注意 URL encode 行為要與現況一致）
- 靜態資產路徑**原樣保留**：`/imgs/**`（og.png、download-og.png、blog 封面全部被絕對 URL 引用）、`/CNAME`

新 IA 增加的路徑（`/data-quality`，未來可能的 `/download/archive`）皆為**純新增**，不影響本清單。

驗收方式：改版分支 build 出 dist 後，用舊站 `dist/` 的檔案清單 diff 新站輸出，
逐條確認上述路徑都有對應檔案（redirect 頁可改用 meta refresh / `<link rel="canonical">`）。

---

## 資訊架構（IA）

> **草稿**：本節仍在持續變動中，尚未定稿；分期表引用本節之處，以本節最新內容為準。

### 現況的問題

現況的頁面是照「資料的存放方式」組織的（編年、全量），不是照「使用者的任務」：

- **`/download` 是編年式全量列表**：9 個年份 × 年/季/月三張表 × 原始/消除重複兩型，
  每年固定 +12 列，只會越來越長。最常見的任務（拿最新完整資料）與新訪客最需要的判斷
  （原始 vs 消除重複差在哪、該下載哪份）都埋在表格海裡，沒有視覺重點。
- **資料品質資訊散落在 blog**：8 篇 data-issue 文章記錄了「某段期間資料遺失 35%」這類
  研究員判斷資料可用性的關鍵事實。download 頁的附註欄有 markdown 連結指向個別文章
  （production 已確認），但它埋在各資料列中、非結構化——沒有一個地方能一眼看出
  「哪些期間的資料要小心」，跨期間的全貌仍得自己翻部落格拼湊。`/data-quality` 的價值
  是彙整成總表，而非從零補上警告。
- **沒有「如何引用」**：記者與研究員只能自行發明引用格式。
- **開發者資訊無站上入口**：S3 URL 規則、schema、爬蟲套件（PyPI）、參與方式散落
  GitHub README 與 about-data-set，站上沒有導流。
- 首頁的「最新資料集」卡片有導流作用，但三種受眾進站後的下一步都一樣，沒有分流。

### 三種受眾的任務

| 受眾 | 進站要完成的事 | 現況卡在哪 |
|---|---|---|
| 記者 | 這是什麼資料、可信嗎、拿最新資料、怎麼引用、找誰問 | 要自己判讀 download 表格與 `schema_ver`/`data_ver` |
| 研究員 | 長期 bulk 下載、欄位/編碼表、資料品質紀錄、版本沿革、引用格式 | 品質紀錄埋在 blog；引用方式不存在 |
| 開發者 | 檔案 URL 規則、schema、爬蟲套件、如何貢獻 | 散落 GitHub/README，站上無入口 |

### 新 IA

```
/                    首頁：mission 一段 + 三張受眾入口卡（我要拿資料／我要做研究／我要參與開發）
                     + 最新發布（沿用現有卡片概念）+ 近期公告
/download            重新設計，解決「越來越長、沒有重點」——三段式：
                       1. 快速下載：最新年度 + 最新月份兩張大卡；一句話選擇指南
                          （原始 vs 消除重複、csv vs json 各自適合誰）
                       2. 如何引用：建議引用格式（含資料版本與擷取日期）+ CC0 說明
                       3. 完整檔案庫：依年份折疊，預設只展開最新一年
                          （若單頁仍太重，再拆 /download/archive，屆時 /download 保留前兩段）
/about-data-set      redirect 改為「版本沿革目錄頁」：列出 0.0–0.3 各版適用期間與變更摘要；
                     0.0–0.3 各版頁面照舊保留
/data-quality（新）   資料品質與已知問題總表：彙整 data-issue 文章成一張時間軸表
                     （影響期間／影響範圍／狀態／詳文連結）；download 檔案庫中受影響的
                     資料列加上指回本頁的警示標記
/blog                照舊；data-issue 類文章繼續用 blog 寫，發佈時同步更新 /data-quality 總表
```

開發者不另立頁面：首頁的開發者入口卡直接指向 GitHub、PyPI 套件與 S3 URL 規則說明
（URL 規則放在 download 檔案庫段落，那正是開發者想寫程式批次抓檔的地方）。

**IA 層面不做**：英文版（受眾以中文使用者為主，維護成本翻倍）；獨立 FAQ 頁
（內容併入 download 的選擇指南）；站內搜尋（站太小，交給搜尋引擎與 sitemap）。

---

## 分期

原則：**新站在獨立目錄（暫名 `ui-next/`）開發，舊站照常部署**，直到 Phase 4 一次切換。
避免長時間 branch 分岔，每期完成即可 merge master（新目錄不影響現行 CI）。

### Phase 0 — scaffold（半天）

| # | 項目 |
|---|---|
| 0-1 | `ui-next/`：Astro + `@astrojs/vue` + Tailwind v4（`npx astro add vue tailwind`）+ `@astrojs/mdx` |
| 0-2 | 基本 layout（header/footer，對應現況 `layouts/default.vue`）+ 首頁骨架（含三受眾入口卡，見〈資訊架構〉） |
| 0-3 | CI：加一條 PR workflow 對 `ui-next/` 跑 `astro check` + build（取代只有 ESLint 的現況） |

### Phase 1 — Download 頁（含重新設計）（1–2 天）

| # | 項目 |
|---|---|
| 1-1 | `stats/*.json` 搬進 `ui-next/src/data/`，schema 用 zod 定型（`comment` 欄位的 string/array 兩型、`download_url.isS3` 等現況慣例要涵蓋） |
| 1-2 | Download 頁依〈資訊架構〉三段式重新設計（快速下載／如何引用／依年份折疊的檔案庫）；元件寫 Vue SFC，折疊用原生 `<details>` 即可不出貨 JS |
| 1-3 | 保留「本表格資料下載 JSON」功能與 S3 連結組合邏輯（`S3_BASE`） |

### Phase 2 — 部落格（1–2 天）

| # | 項目 |
|---|---|
| 2-1 | Content Collection schema + 19 篇 md 原樣搬入；`<!--more-->` 摘要切割工具 |
| 2-2 | 列表頁、單篇頁（含 OG、schema.org microdata 照搬）、tag 頁（中文 slug 驗證） |
| 2-3 | 接入 Cusdis（hosted）：註冊 site、embed 元件化（blog 單篇與 download 頁，對應現況 `TwrhDisqus` 的兩處使用）、審核通知設定 |
| 2-4 | `@astrojs/rss` 出 feed（新功能） |

### Phase 3 — 關於資料集（1 天）

| # | 項目 |
|---|---|
| 3-1 | 0.0–0.3 內嵌 markdown 抽成 `.md`，共用「版本頁」layout |
| 3-2 | TOC 改由 `headings` 產生 + CSS sticky；`/about-data-set` 改為版本沿革目錄頁（0.0–0.3 各版適用期間與變更摘要） |
| 3-3 | 新頁 `/data-quality`：彙整 8 篇 data-issue 文章成時間軸總表；download 檔案庫受影響資料列加警示標記（stats JSON 增加選填欄位 `quality_issue` 指向本頁錨點） |

### Phase 4 — 切換上線（半天）

| # | 項目 |
|---|---|
| 4-1 | URL 保留清單逐條驗收（dist diff） |
| 4-2 | `ui-deploy.yml` 改指向 `ui-next/`（Node 版本一併升級對齊）；GoatCounter embed、site-verification 確認無漏 |
| 4-3 | 觀察一週無異常後：舊 `ui/` 整目錄刪除、`ui-next/` 改名 `ui/`、更新 CLAUDE.md 與 README |

### Phase 5 — 互動統計圖表（時程獨立，需求出現才動工）

- 圖表元件 = Vue SFC + `client:visible`，資料在 build 時從 stats JSON（或另備的聚合 JSON）算好塞 props。
- 文章內嵌圖表走 MDX。
- 圖表庫屆時再選（ECharts / Chart.js / Observable Plot 皆可，與本計畫正交）。

---

## 待拍板

目前無——留言系統（Cusdis）、流量分析（GoatCounter）、Sentry（移除）、download 頁方向
（〈資訊架構〉三段式）皆已拍板。download 頁與首頁的細部視覺於實作時決定。

---

## 何時該升級成 Nuxt（預先寫下訊號，避免屆時重新辯論）

互動從「頁面裡的元件」長成「跨頁面的應用」時才升級，具體徵兆：

1. **跨元件共享狀態**：一組篩選器同時控制多張圖與表格，發現自己在寫第二、三個跨 island 的 store（nanostores）
2. **URL 驅動的探索介面**：`/explore?city=…&year=…` 這類可分享查詢狀態、client-side 路由
3. 需要 server 端 API（動態查資料，而非 build 時預算）

屆時的搬家成本有上限：Vue SFC 元件層（含圖表）、markdown content、Tailwind、stats JSON
全部直接沿用，只重寫十來個 `.astro` 薄入口。這是「Astro 起步不會鎖死」的依據。

---

## 建議不做

| 項目 | 理由 |
|---|---|
| 為了未來 dashboard 現在就上 Nuxt 4 | 讓 95% 純內容的站每頁付 app framework 與 hydration 成本，換取還沒出現的需求；訊號條件見上節 |
| 逐步在 Nuxt 2 內升級（Nuxt Bridge / 漸進遷移） | Nuxt 2→4 是 Vue 2→3、webpack→Vite、Content v1→v3 全換，工作量與重寫相當；700 行的站直接重寫更便宜 |
| 保留 Pug / Tachyons / Buefy | Pug 增加工具鏈依賴無對價；Tachyons 由 Tailwind 取代；Buefy 現況本來就零使用 |
| 把 stats JSON 改成自動產生 | 是資料管線側的題目（export 流程），與 UI 改版無相依；現況手動流程運作正常，不混進這一輪 |
| 舊 blog 文章改寫成 MDX | 19 篇維持 `.md` 原樣，降低遷移 diff；MDX 只給未來要嵌圖表的新文章 |

---

## 實作狀態（2026-08-25）

Phase 0 ～ 4-2 已在 `ui-next/` 完成（Astro 7.2 + Vue 3.5 + Tailwind 4.3，每個 task 一個 commit）：

- Phase 0：scaffold、Base layout（含 GoatCounter、site-verification）、首頁三受眾卡、`ui-next` PR CI（`astro check` + build + URL 驗收）
- Phase 1：stats JSON 搬入 `src/data/stats/` + zod schema；download 頁三段式（快速下載／#cite／#archive 以 `<details>` 依年份折疊）；S3 連結邏輯與「本表格資料下載 JSON」保留
- Phase 2：19 篇 md 原樣搬入 Content Collection、`<!--more-->` 摘要工具；列表／單篇／tag 頁（microdata、OG 照搬）；Cusdis 元件（app id 待註冊，見下）；`/rss.xml`
- Phase 3：0.0–0.3 抽成 `.md`＋共用版本頁；TOC 改 build-time `headings`＋CSS sticky；`/about-data-set` 改版本沿革目錄頁；`/data-quality` 總表＋檔案庫 `quality_issue` 警示標記
- Phase 4-1：`ui-next/scripts/check-urls.mjs` 驗收通過（35 頁 + 27 資產），並掛進 CI
- Phase 4-2：`ui-deploy.yml` 改建置 `ui-next/`（Node 24，移除 Sentry secrets）

**尚待人工處理**：

1. Cusdis：至 cusdis.com 註冊 site 後，把 app id 填入 `ui-next/src/lib/site.ts` 的 `CUSDIS_APP_ID`（留空時留言區不顯示），並在後台開啟審核與通知
2. Phase 4-3：上線觀察一週無異常後，刪除舊 `ui/`（連同 `ui-pull-request.yml`）、`ui-next/` 改名 `ui/`、更新 CLAUDE.md 與 README

---

## 編修紀錄

- **2026-08-25** 建立。決策脈絡：#212（TOC DOM 時序 bug）觸發改版討論；技術選型比較了
  Astro / Nuxt 4 + Content v3 / VitePress / Eleventy，以「零 JS 預設 + Vue SFC 元件層 +
  island 承接未來圖表」拍板 Astro；現況盤點與 URL 清單為同日對 `ui/` 實際檢視的結果
  （當時 Astro 最新為 v7、Tailwind 為 v4.3；Astro 已於 2026-01 被 Cloudflare 收購，仍為 MIT 開源）。
  同日拍板：流量分析 Plausible → GoatCounter（與 8h-probe 同帳號）；留言 Disqus → Cusdis hosted
  （比較過 giscus——發言須登入 GitHub 而出局；CommentBox、Hyvor Talk、自架 Remark42——皆不如
  Cusdis 符合「匿名、免費、免維運、無追蹤」；舊 Disqus 留言不遷移）；Sentry 移除不帶到新站。
  同日新增〈資訊架構〉：以記者／研究員／開發者三受眾任務分析現站，拍板 download 頁三段式
  重設計（快速下載／如何引用／依年份折疊檔案庫，解決「越長越沒重點」）、`/about-data-set`
  redirect 改版本沿革目錄、新頁 `/data-quality` 彙整 data-issue、首頁加三受眾入口卡；
  英文版／獨立 FAQ／站內搜尋列為 IA 層面不做。
