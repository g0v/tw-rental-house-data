# AI 監測／分診／修復（AI triage）計畫

> 建立於 2026-08-20。這份就是 `dx-roadmap.md`〈建議不做〉裡預告的「AI triage 另案」。
> 技術現況（GitHub / Claude / OpenAI Codex 三個生態系的產品與計價）以 2026-08-20 網路查證為準，
> 來源連結見文末；agent 產品迭代很快，超過一季請重新查證再動工。

這份文件回答三件事：**AI 在哪些步驟介入、用哪個平台跑、錢從哪裡出**。

---

## 目標迴圈與第一個原則

1. **偵測**系統性錯誤（591 改版、新防爬蟲機制）→ 停下來、收集資料、回報
2. **分診（triage）**：agent 分析問題、評估修復難度與信心、給建議
3. **人工決策**：確認後才動手
4. **自動修復**：agent 改 parser、驗證、開 PR

第一個原則：**只有 2 和 4 需要 LLM，而且是事件驅動**。
偵測靠確定性斷言（熔斷、填充率、比率門檻——Phase 2 已完成），決策靠人。
「每晚跑一次 AI」是錯的設計；AI 只在告警響起時被喚醒。這讓費用天生可控。

---

## 拍板：訂閱優先（2026-08-20）

維運者有 **Claude Max 5x 訂閱**，AI 執行面一律優先走訂閱額度，不開 API key 計費：

| 面向 | 訂閱能不能吃到 | 依據 |
|---|---|---|
| `claude-code-action@v1`（GitHub Actions） | ✅ 官方支援 `claude_code_oauth_token`（`claude setup-token` 產生，Pro/Max/Team/Ent），用量計入訂閱 | 官方 docs 明載 |
| Claude Code routines（排程／`/fire` API 觸發的雲端 session） | ✅ 計入訂閱，另有每日 run 上限 | research preview |
| Claude Code in Slack（@Claude 起 coding session、給 Create PR 按鈕） | ✅ Pro/Max 可用 | research preview |
| Claude Agent SDK（自建常駐 agent） | ❌ 官方政策：自動化服務要用 API key | 官方 docs 明載 |
| Claude Managed Agents（Anthropic 託管沙箱 + cron） | ❌ API token + $0.08/session-hr | beta |

推論出的選型：**執行面以 `claude-code-action` 為主幹**（fix 與 triage 都是），
routines 與 Slack 整合當補位；Agent SDK／Managed Agents 降為「將來要 org 化交接時」的備案。

已知代價，先記著：

- **OAuth token 綁個人訂閱**。單人維運期沒問題；若專案要交給 g0v 組織層級共管，
  遷移路徑是換成 API key（workflow 只改 secret，不改結構）。
- **訂閱有 5 小時滾動視窗額度**。本案用量是「告警才觸發」，量級遠低於日常 coding，
  但改版搶修期會與人的互動用量疊加——真撞牆時單次 fix 改開 API key 跑即可。
- ⚠️ 未驗證：有第三方回報 2026 年初曾發生 setup-token 在 CI 被拒的波動；
  與現行官方文件矛盾，以官方為準，但 workflow 要寫成「認證失敗 → 通知人」而不是靜默重試。

---

## 三生態系研究結論（摘要）

完整查證記錄太長不進 repo，這裡只留結論與淘汰理由：

| 平台 | 結論 | 理由 |
|---|---|---|
| **Claude**：claude-code-action v1 | **採用（主幹）** | GA、可掛任何 GitHub event（`schedule`／`workflow_run`／`repository_dispatch`）、automation mode 免 @mention、訂閱 OAuth 官方支援、可跑自架 runner |
| **Claude**：routines `/fire` endpoint | 觀察／試水溫 | 官方範例就是「告警觸發 → agent 拉 log → 開 draft PR」，完全對口；但 research preview、綁個人帳號、PR 掛個人身分 |
| **Claude**：Claude Code in Slack | 觀察 | 「人在 thread @Claude 下令修」是最自然的核准介面；research preview，且 session 記個人帳號 |
| **Claude**：Agent SDK / Managed Agents | 備案 | 功能最完整但只能 API 計費；Managed Agents 另收 $0.08/hr、Slack 要自建、還在 beta |
| **GitHub**：Actions 基礎層 | **採用（管線）** | `repository_dispatch`（AWS → GitHub 橋接）與 `workflow_run` 皆 GA；公開 repo 運算免費 |
| **GitHub**：Copilot cloud agent | 不採 | 能力對口（issue 指派、REST API、PR 沙箱）但要另一份訂閱（AI credits 計費），與 Max 重複付費 |
| **GitHub**：gh-aw（Agentic Workflows） | 觀察 | 安全模型最漂亮（唯讀 + safe outputs、引擎可選 Claude Code），但 technical preview，先不當地基 |
| **OpenAI**：Codex cloud / CLI / Action | 不採 | cloud task **沒有公開觸發 API**（只有 Slack/GitHub @mention）；CLI/Action 只吃 API key，等於放棄訂閱優勢；AgentKit 已宣布 2026-11 關閉 |

---

## 對照 roadmap 現況：哪些既有產出改變了設計

2026-08-20 的實作進度（Phase 0、Phase 2、2.5-4 完成）讓這一案比原本設想的更近：

1. **`twrh survey` 的報告就是 triage 的證據包。**
   survey 輸出的是聚合統計（成功率、`property_type` 分布、每欄位填充率 vs baseline），
   **不含個資** → 可以直接上傳 GitHub（issue 附件／Actions artifact），
   triage agent 不必為了讀證據而住在 AWS。這推翻了研究初期「triage 必須跑在資料所在地」的預設。
   只有 raw HTML 樣本仍受個資約束：留在自架側，或走 1-4 scrub 後才進 repo。
2. **觸發點已經存在，不用等 L2/L3。**
   2-1 熔斷（`close_spider` + 自訂訊號）、2-2 填充率告警、2-3 statscheck 比例門檻——
   三個都是「確定性偵測已判定異常」的訊號，接上 `repository_dispatch` 就是 triage 的入口。
   L2/L3（3-2）做完後只是多兩個更早期的入口，架構不變。
3. **2.5-4 CLI 是現成的 agent 工具箱。**
   fix agent 驗證自己的改動不需要任何新基建：`twrh parse <html>` 離線驗 parser、
   `twrh survey` 量測填充率。CLAUDE.md 已記載用法，claude-code-action 起的 session 讀得到。
   **這是「工具給人用也給 agent 用」的紅利——之後所有診斷工具都照這個標準做。**
4. **1-3 golden 測試（未做）是 fix 自動化的硬前置。**
   沒有離線 golden CI，agent 開的 PR 無法自我驗收，等於叫人肉眼審 selector——那不如人自己修。
   所以 fix 自動化（A2）排在 1-3 之後；triage 自動化（A1）不依賴它，可以先行。

---

## 分階段

### A0 — 手動觸發的 agent（現在就可做，半天）

- repo secrets 加 `CLAUDE_CODE_OAUTH_TOKEN`（`claude setup-token` 產生）。
- 裝 `anthropics/claude-code-action@v1` 的 interactive workflow：issue／PR 留言 `@claude` 觸發。
- 用法：Slack 告警響 → 人開 issue 貼上 statscheck／survey 摘要 → `@claude 分析這次告警，
  對照 docs/dx-roadmap.md 的分層維度，評估是 selector 漂移還是防爬蟲，給修復難度與信心`。
- 這一步零新基建、零 API 費，先累積「agent 對這個 codebase 的分診品質」的手感，
  順便驗證 OAuth token 在 CI 的穩定性（見上面的未驗證事項）。

### A1 — 告警自動開 issue + 自動分診（Phase 2 已就位，可接著做）

- `statscheck`／熔斷告警時，除了發 Slack，同時帶 payload 呼叫
  `POST /repos/g0v/tw-rental-house-data/dispatches`（fine-grained PAT，只給 contents:write）。
- `repository_dispatch` 觸發 claude-code-action **automation mode**：
  讀 payload 裡的證據（survey JSON diff、錯誤統計）→ 開一張結構化 issue：
  症狀分類（會被算到／靜默消空）、疑似原因、修復難度、信心、建議下一步。
- **人工決策閘 = issue 本身**：人看完在 issue 留言 `@claude 修吧` 才進入修復；不留言就什麼都不發生。
- Slack 端只要把 issue 連結貼進告警訊息，既有 bot 不用大改。

### A2 — 核准後自動修復開 PR（依賴 1-3 golden CI）

- `@claude` 修復指令觸發 fix session：改 parser → 跑 L1 golden + `twrh parse` 舊版式回歸 →
  開 PR，PR 描述附「改動前後的填充率對照」。
- 需要連網驗證（打 591 實測新 selector）的步驟**不在公開 GitHub Actions 跑**
  （承襲 roadmap〈建議不做〉的道德約束）——兩個解法擇一：
  (a) fix agent 只做離線部分，PR 上標註「待自架側 survey 驗證」，由人在本機／AWS 跑 `twrh survey` 貼結果；
  (b) 自架 runner 掛 `runs-on: self-hosted` 的驗證 job（token／proxy 都在自己機器上，不進公開 CI）。
  先用 (a)，量大了再上 (b)。
- PR 一律人審後才 merge；Claude App 的 commit 不觸發後續 CI 是預設安全行為，維持不變。

### 之後的可能性（不排程）

- L2/L3 nightly 就位後，把 L3 drift 告警接進 A1 同一個入口。
- routines `/fire`／Claude Code in Slack 轉 GA 後，評估用它們取代 A1 的膠水 workflow。
- 加第二個租屋站點（4-6）時，AI triage 的 prompt 與證據包格式要跟著 vendor 抽象走。

---

## 費用

- **訂閱內邊際成本 ≈ 0**：A0–A2 的用量（正常月幾次 triage、改版月每天數次）遠低於 Max 5x 額度；
  公開 repo 的 GitHub Actions 運算免費；自架 runner 免 Actions 分鐘費。
- **API fallback 參考價**（2026-08 牌價，撞訂閱額度時用）：
  Sonnet 5 $2/$10 per MTok（已定為正式價）、Opus 5 $5/$25、cache read 0.1×。
  單次 triage（~500K in/30K out）Sonnet 上限 ~$1.3；單次 fix（~2M in/60K out）Opus 上限 ~$11.5，
  快取命中後常見 4–6 折。
- 對照組（不採用，留數字供將來重估）：Copilot Pro $10/月含 $15 credits（用量計費制）；
  Codex 走 ChatGPT 方案 $20 起或 GPT-5.6 API（Terra $2/$12）；Managed Agents 另加 $0.08/session-hr。

---

## 建議不做（本案範圍）

| 項目 | 理由 |
|---|---|
| 自建 Agent SDK 常駐 triage 服務 | 單人維運 + 訂閱優先的前提下是多餘工程，且只能 API 計費。留作 org 化交接時的備案 |
| 現在採用 gh-aw / routines / Claude Code in Slack 當地基 | 全是 preview；等 GA 再評估取代 A1 膠水 |
| 讓 agent 自動 merge 或自動觸發正式爬蟲 | 決策權在人。agent 的產出止於 PR 與報告 |
| 把 raw HTML 證據上傳公開 repo | 個資（電話／地址）。聚合報告可上，raw 樣本留自架側或 scrub 後才進 |
| 用 Copilot cloud agent / Codex 當執行面 | 與 Max 訂閱重複付費；Codex 缺程式化觸發 API |
| AI 分診「靜默消空」以外的資料品質問題 | 那是 2-2 填充率監控的職責；AI 只接手「已判定異常之後」的分析 |

---

## 未驗證／時效性事項

1. OAuth token 在 GitHub Actions 的長期穩定性（官方支援，但有第三方回報過波動）。
2. Max 5x 額度換算成 token 的實際上限（Anthropic 不公布；以實測為準）。
3. routines 每日 run 上限的具體數字（帳號內查看）。
4. gh-aw、routines、Claude Code in Slack 的 GA 時程。

**主要來源**（2026-08-20 查證）：
[claude-code-action](https://github.com/anthropics/claude-code-action)、
[GitHub Actions 整合官方文件](https://code.claude.com/docs/en/github-actions)、
[Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview)、
[routines](https://code.claude.com/docs/en/routines)、
[Claude Code in Slack](https://code.claude.com/docs/en/slack)、
[Claude API 定價](https://platform.claude.com/docs/en/about-claude/pricing)、
[repository_dispatch](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)、
[Copilot 用量計費公告](https://github.blog/news-insights/company-news/github-copilot-is-moving-to-usage-based-billing/)、
[gh-aw](https://github.github.com/gh-aw/)、
[Codex 文件](https://learn.chatgpt.com/docs/cloud)。
