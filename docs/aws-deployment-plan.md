# AWS 部署規劃（排程爬蟲 + 中繼檔 + 臨時工作機）

> **草稿（2026-08-26 起），尚未實作，內容仍會隨評估與量測持續變動。**
> 目標：把目前「本機手動 go.sh」的接手狀態轉回雲端例行運作，
> 取代舊的 EC2 master/child + crontab + `devop.tgz` scp 模式（見 `twrh-dataset/devop/devop.md`）。

## 需求（拍板的五條）

1. 每天一次所有平台全量下載；排程組合未來會變（例：平日只跑新的、週末全量），系統要有彈性。
2. Deploy 新 code 不用手動逐台處理。
3. Log 留存；中繼檔要落地（export 產出的 `datas/` zips、`publish/<YYYYMM>.state.json`、
   月報 json、`logs/progress/`——見 `docs/export-automation-plan.md`）。
4. 方便開臨時機：碰得到中繼檔與 DB（正式環境已是 AWS RDS PostgreSQL），附 Adminer。
5. 費用合理即可，不犧牲方便性；可以用執行速度、開機速度換費用。

---

## 建議組合（一句話版）

**一顆 container image（ECR）＋ ECS Fargate 排程任務（EventBridge Scheduler）＋
EFS 掛載中繼檔 ＋ CloudWatch Logs ＋ 既有 RDS；臨時機 = 同一顆 image 用 `run-task` 開，
Adminer 是一個 desired-count 0 的 Fargate service，要用才轉 1。**

沒有常駐主機、沒有 NAT Gateway、沒有 K8s。RDS 以外的新增費用估 **~US$7–10/月**。

```
GitHub push ──▶ GitHub Actions build ──▶ ECR image
                                            │
   EventBridge Scheduler（cron, Asia/Taipei）│
   ├─ 每日 20:03  ./go.sh          ─────────┼──▶ ECS Fargate task ──┬─▶ RDS PostgreSQL（既有）
   ├─ (未來) 平日 ./go.sh --append          │      │                ├─▶ EFS：logs/、datas/、progress/
   └─ (未來) 週六 ./go.sh 全量              │      └─ stdout ──────▶ CloudWatch Logs（設保留期）
                                            │
   人工出貨：aws ecs run-task publish.sh ───┘（同 image 的 publisher target，見下）
   臨時機：  aws ecs run-task workbench ＋ ECS Exec 進 shell；Adminer service 0→1
```

---

## 需求逐條對應

### 1. 排程彈性 → EventBridge Scheduler，一條排程 = 一組 command override

- 每個「平台 × 模式」是一條 schedule，內容只是 cron 表達式 + task 的 `command` override，
  例如 `["./go.sh"]`、`["./go.sh","--append"]`、未來 `["./go-<vendor>.sh"]`。
- 改組合（平日增量、週末全量、加新平台）＝加／改一條 schedule，**不動 code、不動 image**。
- EventBridge Scheduler 原生支援時區（`Asia/Taipei`），不用再算 UTC 偏移；也支援
  one-off 排程（`at()`），補跑某天可用 `--date`（`export` 不吃 `TWRH_TARGET_DATE`
  的舊 caveat 已於 2026-08-28 修掉——export 現在與 pipeline 其他環節同日期語意）。
- go.sh 的 detail batch 重啟迴圈整段跑在同一個 task 裡，Fargate 對執行時長沒有上限
  （全台全量實測數小時內完成）。`gobg.sh` 的 setsid 背景化在容器裡不需要，直接跑 `go.sh`，
  stdout 就是 log。

### 2. Deploy → push 即完成，沒有「台」可言

- GitHub Actions 在 push master（或打 tag）時 build image 推 ECR，task definition 指向
  `:latest`（或由 CI 更新 digest）。**下一次排程自然吃到新 code**，要立即生效就手動
  `run-task` 一次。
- 舊模式的 `devop.tgz`（gitignored 的 `crawler/settings.py`、`settings_local.py`）改為：
  非機密設定用環境變數（task definition 內），機密（DB 密碼、Slack webhook、Sentry DSN、
  proxy token）放 **SSM Parameter Store（SecureString）**，由 task definition 的
  `secrets` 注入成環境變數。需要一次性小改：讓 `settings.py` / `settings_local.py`
  從環境變數讀值（`.env` 機制已存在，順勢統一）。**機密永遠不進 image**——與
  「token 不可發布」的既有原則一致。
- Dockerfile 一份、兩個 target：
  - `crawler`：Python 3.10 + GDAL/GEOS/PROJ + poetry install，跑 go.sh／management commands。
  - `publisher`：在 crawler 之上加 clickhouse（`csv-aggregator` 用）、awscli、git，
    跑 `publish.sh`。分開是為了讓每天要拉的 crawler image 保持小顆。

### 3. Log 與中繼檔 → CloudWatch Logs ＋ EFS

- **stdout → CloudWatch Logs**（awslogs driver），log group 設保留期（建議 90 天），
  超過自動清，不會無限長費用。breaker 的 `error_rate_exceeded` 之後可直接掛
  metric filter 告警（不在本期範圍）。
- **watchdog 的雲上對應**（2026-08-28 補）：本機 `twrh-dataset/watchdog.sh` 的職責
  在 Fargate 由 CloudWatch 接手，其中**零產出斷言必須保留**——「FINALIZE 但
  progress 為零」的靜默失敗真實發生過（scrapy 2.18 不呼叫 start_requests，
  pipeline 5 秒無錯誤地「正常」跑完），形態上 metric filter 告警或 statscheck
  自我檢查皆可，A4 上線前落地。
- **檔案類全部放 EFS**，掛進每個 task 的 `twrh-dataset` 工作目錄外層：
  - `../logs/`（go.sh 搬過去的 scrapy log、`logs/progress/<date>.detail.json`、fill-rates）
  - `datas/`（export 的月 zip——**publish 前的中繼檔**，紅燈月會在這裡停留到人工補完敘事）
  - `datas/publish/<YYYYMM>.state.json`（publish.sh 冪等 marker）
  - 月報 `<YYYYMM>.report.json`
- EFS 是 POSIX 檔案系統，`go.sh`／`publish.sh` 的相對路徑**完全不用改**；task 之間、
  排程任務與臨時機之間天然共享同一份狀態。開 lifecycle（30 天未存取轉 IA）壓費用。
- 長期封存（`archivehistory` 的 tar、超過一季的舊 log）再從 EFS 丟 S3，EFS 只留工作集。

### 4. 臨時機 → 同一顆 image + ECS Exec；Adminer 開關式 service

- `devop/aws/workbench.sh`（新增的小 wrapper）做兩件事：
  1. `aws ecs run-task` 起一個 crawler（或 publisher）image 的 task，command 為
     `sleep infinity`，掛 EFS、帶 DB secrets——**環境與排程任務完全一致**；
  2. `aws ecs execute-command` 進 shell。進去就是 `poetry run python django/manage.py
     dbshell`、`twrh probe`、檢查 `datas/` 都可用。用完 `stop-task`，成本以分計。
- **Adminer**：一個 desired count = 0 的 Fargate service（官方 `adminer` image，
  0.25 vCPU 就夠）。要用時 `update-service --desired-count 1`，連線方式二選一
  （見開放問題 3）：
  - a. task 拿 public IP，security group 只放行自己當下的 IP（wrapper 自動抓 `curl ifconfig.me` 填入）；
  - b. 不開對外，走 SSM port forwarding（ECS Exec 底層即 SSM agent）轉 8080 到本機。
  用完 desired count 歸 0，平時零費用。
- RDS 的 security group 收斂為只允許 ECS tasks 的 SG（取代舊時代的公網開放）。

### 5. 費用 → 常駐項目歸零，用「跑多久算多久」換

| 項目 | 估算（月） | 備註 |
|---|---|---|
| Fargate 每日 crawl | ~US$4–5 | 1 vCPU / 2GB × 數小時/日（本機實測瓶頸在網路、CPU 需求低）；ARM64（Graviton）再省 ~20%，GDAL/clickhouse 都有 aarch64 版 |
| EFS | ~US$1–2 | 工作集數 GB，IA lifecycle |
| CloudWatch Logs | <US$1 | 每日 log 數十 MB，90 天保留 |
| ECR | <US$0.5 | 兩個 image target |
| EventBridge Scheduler、Adminer/workbench 偶發時數 | ~US$0 | |
| **合計（RDS 另計，既有）** | **~US$7–10** | |

#### Fargate task 開多大

初版 **crawler task：1 vCPU / 2 GB（ARM64）**，依據：

- Scrapy 是單行程單執行緒（twisted event loop），**>1 vCPU 用不到**——多 vCPU 只在
  未來多 spider 平行時才有意義。detail 全速時瓶頸在網路往返，不在 CPU。
- 記憶體有制度性上界：persist queue 在記憶體最多 `queue_length=30` 個請求、
  detail spider 每 `batch_size=2000` 筆重啟一次行程——這兩個機制本來就是為了
  bound memory 設計的。
- Fargate 的 vCPU 是足額配給（不是 burstable），1 vCPU 持續輸出對單 spider 綽綽有餘。
- 費用敏感度低：數小時/日之下，0.5→1→2 vCPU 每檔差距僅 ~US$2/月——**拿不準就開大一級**，
  不值得為此冒 OOM 風險。
- **實測結果（2026-08-27 全量，60s 取樣）**：scrapy RSS 峰值 ~240 MB（list 段），
  detail 段穩定 ~165–190 MB；CPU 峰值約半顆核心。**1 vCPU / 2 GB 定案**，
  餘裕充足（本次跑在行動網路、速率偏低，CPU 按全速放大一倍仍 <1 vCPU）。
  本機 postgres 峰值 ~1.1 核、記憶體 ~175 MiB——支持 RDS t4g.small 起跳的判斷。
- **batch_size 驗證結果**：以 **10000** 實跑全量（8 個 batch），批內與跨批 RSS
  **全程平坦無爬升**——playwright/OCR 移除後 memory leak 確認消失，
  `batch_size=2000` 的保險可正式放大；未來可考慮直接取消重啟迴圈，
  restart 開銷與 progress 記帳跟著簡化。go.sh 已支援 `DETAIL_BATCH_SIZE`
  環境變數覆寫。

刻意避開的費用陷阱：
- **不開 NAT Gateway**（固定 ~US$32/月＋流量）：task 放 public subnet 直接拿 public IP 出網。
- **不留常駐 EC2**：連 Adminer 都是開關式。
- 可選再省：Fargate **Spot**（約 -70%）。persist queue 本來就 resumable、go.sh 冪等，
  中斷重跑理論上無害——但 EventBridge 不會自動重啟被回收的 task，需要多一層重試
  （AWS Batch 或 retry wrapper）。**建議先用 on-demand**，一個月省不到 US$4，
  不值得第一版就加複雜度；列入 Backlog。

---

## 與 export-automation-plan 的銜接

- `publish.sh` 的「人工觸發」原則不變：轉到 AWS 後，出貨動作變成本機一行
  `devop/aws/publish.sh YYYYMM`（wrapper，內部 `run-task` publisher image）。
  中繼檔在 EFS 上，紅燈月的「補敘事 → `--resume`」流程照走。
- publish 需要的 S3 上傳憑證改由 **task role** 提供（`s3:PutObject` 限
  `twrh` bucket `/<year>/*`），開放問題 1「S3 憑證進本機？」就地消解——憑證根本不進本機。
- UI stats json 的 commit/push 需要 GitHub 憑證（deploy key 或 fine-grained PAT），
  放 SSM，只注入 publisher task。

---

## 建議不做

| 項目 | 理由 |
|---|---|
| EKS / K8s | 一天一個 task 的工作量，管理面成本完全不成比例 |
| Lambda | 15 分鐘上限，pipeline 一跑就是數小時 |
| Step Functions 拆 pipeline 步驟 | go.sh 已是可靠的 orchestrator（breaker 中止、batch 重啟、progress 續跑都在裡面），拆出去是平移複雜度不是消除 |
| 回到 EC2 + crontab | 就是要淘汰的模式：deploy 要上機、機器要顧、cron 改排程要 ssh |
| AWS Batch（第一版） | 只為了 Spot 重試而引入一整套 queue/compute environment；留 Backlog |
| 自架 PostgreSQL on EC2 | RDS 既有且含 PostGIS，遷移零收益 |
| 常駐 Adminer / bastion | 一年用不到幾小時的東西不該 24×7 計費 |

---

## 分階段實作（依賴順序）

| # | 項目 | 成本 | 說明 |
|---|---|---|---|
| A1 | Dockerfile（crawler/publisher 兩 target）＋ settings 全面環境變數化 | 中 | 唯一動到 code 的一段；本機 docker run 對 local PostGIS 驗證 go.sh 全程 |
| A2 | AWS 基礎建設：VPC public subnet、ECR、EFS、ECS cluster、task definitions、SSM 參數、IAM（task role 最小權限） | 中 | 建議用 Terraform 或 CDK 收在 `devop/aws/`，一次寫完可重建 |
| A3 | **風控探測**：用 workbench task 從 Fargate IP 跑 `twrh probe`／小城市 survey，**大阪與 us-west-2 兩區各跑** | 小 | 本機量測來自住宅 IP；**AWS 資料中心 IP 段是否被 591 差別對待未知**，這是整個計畫的前提假設，要先驗（見開放問題 2）；兩區結果同時是 region 拍板依據（開放問題 1） |
| A4 | EventBridge 排程上線：先單條「每日全量」，與本機手動跑並行驗證數日後切換 | 小 | 本機退役為備援 |
| A5 | workbench.sh / Adminer service / publish wrapper | 小 | QoL 收尾 |
| A6 | CI：GitHub Actions build & push ECR | 小 | 完成「push 即 deploy」閉環 |

---

## RDS 費用節省

### 資料量實測（2026-08，現行 DB，涵蓋 2025-10 起）

| Table | 總大小 | 佔比 | 說明 |
|---|---|---|---|
| `house_etc` | **52 GB** | **96%** | detail_raw 36 GB＋list_raw 1.8 GB（TOAST 壓縮後）＋detail_dict 1 GB；586k 列、平均 ~90 KB/件 |
| `house_ts` | 1.6 GB | 3% | 1.5M 列，~1.2 KB/列（含索引） |
| `house` | 0.8 GB | 1.5% | 586k 列 |
| 其餘全部 | <0.15 GB | — | request_ts、stats、author…… |
| **合計** | **~54 GB** | | **成長率：raw 貢獻 ~5 GB/月**（~60k 新物件/月 × 90 KB） |

歷史總量（migration 對象）：網站資料集頁推估 2018–2026 累計 **~8.84M 筆月資料列**
（2018: 0.7M → 2022: 1.4M/年；公開 zip 總計 CSV 3.3 GB＋JSON 11.8 GB）。

### AWS 實測補記（2026-08-26，read-only 盤點）

- **既有 RDS**：`twrh` @ us-west-1，**db.t4g.micro、100 GB gp2、Single-AZ**、PG 15.17、
  Publicly accessible = No、2023-12-30 建。**已用 ~85 GB／剩 15 GB**（CloudWatch）。
  估算月費 ~US$24（instance ~$12＋gp2 storage ~$12）。
  兩個直接推論：
  - t4g.micro（1 GB RAM）撐完了 2024–2026-04 的例行爬蟲——原估的 t4g.medium 過大，
    **t4g.small 起跳、micro 也可一試**，費用往 ~US$12–24/月修正。
  - 剩 15 GB 餘裕不多。穩態成長率因重複刊登覆寫（見下）低於本機量到的 5 GB/月，
    不至於三個月就滿，但 gp2 只能加不能減——要瘦身終究得開新機，
    「開新 instance 邊剝邊搬」的方向不變。
- **S3 `twrh` bucket**（ap-northeast-3）：共 443 物件、**20 GB，全部 STANDARD**
  （~US$0.5/月，歷年公開 zip 為主，量小不值得動 storage class）。
  另有空 bucket `twrh-w1`（us-west-1）。
- **重大發現：`s3://twrh/misc/annual-dump/`** —— 2026-04-29/30（例行爬蟲停機前後）
  做過一輪 **house_etc 歷年 dump（2018–2026，47 個 jsonl.gz，共 11.5 GB）**。
  抽驗內容：每列只有 `house_id / vendor_id / vendor_house_id / created / updated /
  detail_dict`——**沒有 detail_raw / list_raw**。
- **舊 RDS 就是全部歷史（ddio 證言，2026-08-26）**：raw HTML 都在裡面，85 GB 即
  2018 年起的總和。歷史 raw 沒有想像中大的原因是**重複刊登**——許多舊物件下架後
  重新刊登，會覆寫既有 house_etc 列的 raw 而非新增列，所以 house_etc 不隨年線性
  成長。推論：本機量到的「raw +5 GB/月」是接手初期的全量首收，穩態成長率會低於
  此值（新物件淨增量 < 每日爬量）；瘦身估算偏保守方向，不影響結論。
- Cost Explorer 被 Organization 的 payer 帳號擋住，實際帳單需從主帳號看；
  上面費用為定價推算。
- **實帳單比對（2026-08-28，以 2025-10 月帳單核對）**：定價推算與實帳相符
  （RDS 單價、storage 單價均驗證）；帳單另揭露約四成為閒置資源費
  （停機機器殘留的 EBS、閒置 IPv4、誤開的 DevOps Guru、超額備份——均已清理）。
  結論校準：新方案（t4g.small、無 RI）名目費用與清理後現況相近，
  內容從「養一台快滿的 DB」變成「每日例行爬蟲＋瘦身後有成長空間」；
  RI 或 micro 撐得住則再省二至四成。
- **偵察第二輪（2026-08-28，scoped profile `twrh` 就緒後）**：
  - scoped IAM profile ✅ 已建（user `twrh-agent`，照
    `devop/aws/policies/migrate-dev-profile.json`，實測確實無 RDS 權限——
    scope 生效的反面驗證）。
  - annual-dump 完整性抽驗 ✅：gzip 完整、JSONL 可解析、欄位如前述 6 欄
    （以 2021_007 抽測；47 檔 11.48 GB 與 4/29 盤點一致）。
  - pricing API 現價對比 ✅：見開放問題 1 的表。
  - **未竟**：RDS snapshot 清單、舊 RDS CloudWatch 指標、route table 再試——
    這三項要 `twrhro`（唯讀 profile），其憑證已失效（InvalidClientTokenId），
    待輪替後補跑；或延後到 A5 workbench 從 VPC 內查。

### 三個節省槓桿（依大小排序）

**1. Raw HTML 出 DB、進 S3（96% 的槓桿）**

Raw 的唯一用途是事後 re-parse（`tools/rerun_detail_raw.py`，修 parser bug 後重跑），
且實務上只會 re-parse 近期資料——冷資料放 DB 是純浪費：
52 GB 在 RDS gp3 是 ~US$6/月且持續增長；同樣資料在 S3 Glacier IR 是 ~US$0.2/月。

- **常態機制（案 A，改動最小）**：pipeline 照舊寫 DB；擴充既有的 `archivehistory`
  （或新 command）為「**raw offload**」：把超過保留窗口（建議 90 天）的
  `detail_raw`/`list_raw` 批次打包上 S3 後清空欄位（`detail_dict` 留在 DB，查詢有用）。
  排程每月跑一次（又一條 EventBridge schedule）。DB 內 raw 穩態維持 ~15 GB 滾動窗口，
  近期資料的 rerun 工具照常可用。house_etc 加一個 `raw_archived_at`（或 S3 key）
  標記欄位，讓 rerun 工具對已剝列明確報「需從 S3 撈」而非靜默拿到 NULL——
  唯一的 schema 微調，不動寫入路徑。
- 打包格式：`s3://<bucket>/raw/<vendor>/<YYYY-MM>.tar.zst`＋同名 index json
  （house_id → offset）。按月打包而非逐檔上傳：逐檔 63 KB 會踩 Glacier IR 的
  128 KB 最低計費與 53 萬次 PUT 請求費；打包則一個月一個物件。要讀時 workbench 拉包解開。
- Storage class：Glacier Instant Retrieval（US$0.004/GB/月，可即時讀）。
  「基本上不會用到」的存取模式正是它的設計目標。
- 案 B（pipeline 直寫 S3、DB 完全不存 raw）改動大（寫入路徑多外部依賴、失敗語意
  要重新設計、rerun/invalidate 全要改讀 S3、本地開發環境失去零雲相依），
  **列 Backlog**，等案 A 跑順且真有痛點再議（2026-08-28 重新確認維持案 A）。

**2. HouseTS 滾動窗口（成長率槓桿）**

每日 snapshot 的下游用途只有兩個：`syncstateful` 算出租所需時間（`n_day_deal`，
只需近期 TS）、月度 export（只需當月）。**export 出貨之後，該月 TS 在公開 zip 裡
就有一份永久副本**（公開資料集本身就是 TS）——DB 沒有理由重複持有。

- 保留窗口建議 **90 天**（涵蓋：deal 判定回看、月結 export、紅燈月 `--resume`、
  invalidate 回溯；既有 `archivehistory` 預設 60 天，代表 60 天已是驗證過的安全線）。
- 窗口外的 TS 由 archivehistory 歸檔到 S3（現在是本機 tar，改個輸出目標）後刪除。
  穩態 house_ts 從無限成長變成 ~0.5 GB 固定。

**3. Instance 選型與購買方式**

- **db.t4g（Graviton burstable）**：負載型態是「一天重度寫數小時＋零星查詢」，
  burstable 正好——白天攢 CPU credits、晚上爬蟲時燒。實測補記：舊 instance 用
  **t4g.micro** 就撐完了例行爬蟲，故從 **t4g.small**（~US$24/月）起跳觀察即可，
  行有餘力再試 micro（~US$12/月）。
- **寫入速率差異（ddio 提醒，micro 經驗不可直接外推）**：舊 micro 驗證的是
  「同量資料攤平在 ~8 小時」的寫法；本機接手後以數倍速塞完（每筆含 ~90 KB raw）。
  這是 t4g.small 起跳的另一個理由；
  storage 一定要 **gp3**（基準 3000 IOPS——舊機 100 GB gp2 只有 300 IOPS，
  高速塞入下很可能先撞 IO 而非 CPU）。A4 與本機並行驗證期間盯 CloudWatch 的
  WriteLatency / CPUCreditBalance / FreeableMemory，不夠就升一級——Modify
  是幾分鐘的事。2026-08-27 全量的本機 postgres 量測（見 Fargate sizing 節）
  也會給出 DB 端參考值。
- **Single-AZ**：資料可重爬、公開 zip 就是異地備份，不值得為它付 Multi-AZ 的 2 倍。
- **gp3 storage、開小顆**：瘦身後穩態 DB 約 25–40 GB，allocate 50 GB（~US$6/月）即可。
  注意 **RDS storage 只能長不能縮**——這是「遷移到新 instance」和「瘦身」必須併案的原因，
  也是為什麼要先 offload 再遷、而不是遷完再清。
- Sizing 穩定後買 **1 年期 Reserved Instance**（no-upfront 約 -30%）。
- 備份維持預設（7 天 automated snapshot，100% allocated 內免費）。

### 瘦身前後對比（估）

| | 放著不管（一年後） | 瘦身後穩態 |
|---|---|---|
| DB 大小 | ~115 GB 且持續 +5 GB/月 | ~25–40 GB 固定 |
| Storage 費 | ~US$13/月 ↗ | ~US$6/月（50 GB allocated） |
| Instance | 記憶體/cache 壓力隨 DB 長 | t4g.small–medium 足夠 |
| S3（raw＋TS 歸檔） | — | ~US$1–3/月（Glacier IR，含歷史全量） |
| **RDS 合計** | 只增不減 | **~US$30–55/月**（RI 後再 -30%） |

---

## 資料遷移（歷史總和 → 新 RDS，分批）

**方向**：不沿用既有 RDS instance 原地改（storage 縮不回來、instance 世代未知），
**開新的小 RDS，把資料「邊剝邊搬」進去**，舊 instance 驗證後關閉。

分批處理的單位與順序：

```
0. 前置查證（部分已完成，見〈AWS 實測補記〉）：剩 in-DB 部分——舊 RDS 85 GB 的
   組成（house_ts 幾年份？house_etc 還有多少 raw？）、歷年 archivehistory tar 的下落
1. 小表一次搬：vendor / sub_region / rental_author / crawlerrequest_stats
   （pg_dump 直灌，數十 MB，分鐘級）
2. **歷史段先跑**（舊 RDS 2018–2026-04，在 workbench task 上跑、AWS 內網）：
   house / house_ts 依 id range 分批 \copy（devop.md 既有的 500k 列/批 pattern），
   每批完成寫 state marker，斷點續跑——與 persist queue 同哲學；
   house_etc 走「剝離式搬運」——**單趟讀全欄位**：detail_raw/list_raw 打包上 S3
   （沿用常態 offload 的格式與 bucket）、其餘欄位（含 detail_dict）進新 DB、寫 marker
   （歷史 raw 是舊 RDS 85 GB 的主要成分，只過境、不進新 DB；這是歷史段最大工作量）。
   annual-dump（s3://twrh/misc/annual-dump/）**降級為對帳基準＋備援**（2026-08-28）：
   它是 2026-04-29 的獨立快照，用於步驟 5 抽樣比對 detail_dict，以及舊 RDS
   大掃描出狀況（t4g.micro 1 GB RAM、burstable credits）時的第二來源——
   不再是資料主線，因為歷史段反正逐列過舊 RDS，同趟帶走 detail_dict 成本為零、
   且欄位比 dump（僅 6 欄）完整
3. **本機段後跑**（2025-10 起，在開發機跑）：同一套剝離腳本對 local PostGIS——
   raw 打包上 S3（~36 GB，家用頻寬分晚跑）、其餘 \copy/upsert 進新 RDS（~5 GB）；
   後跑讓重疊段的本機新值自然蓋過歷史舊值（見開放問題 8 的 upsert guard）
4. 所有 insert 一律帶 `updated` 時間戳 upsert guard（開放問題 8），批次重跑冪等
5. 驗證：各表 row count 對帳、抽樣比對（含 annual-dump 交叉驗證）、
   export dry-run 產出與既有公開 zip 對比
6. 切換：爬蟲排程指向新 DB（改一個 SSM 參數）；舊 instance 停機留 snapshot 一個月後刪
```

停機窗口幾乎為零：爬蟲一天只跑數小時，其餘時間都是遷移空檔；
最後的增量補批（搬運期間新寫入的部分）選在當日 pipeline 結束後做，再切換。

風險備註：
- **本機全套彩排（零 AWS 相依，最先做）**：✅ 已完成（2026-08-28，`tools/migrate/`）
  ——local PostGIS 空 DB `twrh_new` 扮新 RDS、本機目錄扮 S3，本機全量 60.6 萬列
  跑完：全表對帳一致、抽樣比對通過、中斷續跑與 upsert guard 語意實測正確。
  兩個關鍵實測：**zstd 打包壓縮比 ~24×**（本機 114 GB 未壓 raw → 4.85 GB 包，
  Glacier IR 上的歷史全量會遠小於原估）；全程約 1.5 小時、滾動刪包下磁碟峰值
  僅個位數 GB——歷史段 85 GB（TOAST）可在 workbench 一至兩個工作階段內完成。
- 現行資料（2025-10 起這份）出境流量 ~5 GB dump＋36 GB raw 上 S3——
  家用頻寬跑得動，分批分晚跑即可。
- **權限模式**：遷移用 IAM user/role 以最小 scope 開（新 RDS 連線、指定 S3
  prefix 讀寫、ECS run-task/exec、SSM 讀），設為開發機 named profile；
  舊 RDS 另開 DB 層 read-only user。**舊 instance 停機／刪除／snapshot 清理
  不在 policy 內，永遠人工執行**——破壞性操作做到結構上不可誤觸。

---

## 開放問題

1. **Region**：✅ **拍板 us-west-2（Oregon）**（2026-08-28，A3 完成）。
   拍板依據：(a) pricing API 現價對比（見下表）——Oregon 全面便宜；
   (b) A3 風控探測兩區各跑一次 `twrh probe 花蓮縣`（Fargate task、無 proxy）
   ——**兩區全 PASS**（list 量、detail 200 率、parse 率、舊版式哨兵、填充率
   全過），591 未對 AWS 美日 IP 段差別待遇，風控無否決 → 按費用選 Oregon。
   樣本量小（20 筆 detail／單次），A4 與本機並行期是持續驗證；若正式期被擋，
   備案仍是掛 proxy（見開放問題 2）。

   **現價對比（2026-08-28，pricing API，on-demand）**：

   | 項目 | 大阪 ap-northeast-3 | Oregon us-west-2 | 大阪貴 |
   |---|---|---|---|
   | RDS db.t4g.micro | $0.025/hr（$18.25/月） | $0.016/hr（$11.68/月） | +56% |
   | RDS db.t4g.small | $0.051/hr（$37.23/月） | $0.032/hr（$23.36/月） | +59% |
   | RDS gp3 storage | $0.138/GB-月 | $0.115/GB-月 | +20% |
   | Fargate ARM vCPU | $0.04045/hr | $0.03238/hr | +25% |
   | Fargate ARM 記憶體 | $0.00442/GB-hr | $0.00356/GB-hr | +24% |
   | S3 Standard | $0.025/GB-月 | $0.023/GB-月 | +9% |
   | S3 Glacier IR | $0.005/GB-月 | $0.004/GB-月 | +25% |

   穩態月費試算（t4g.small＋50 GB gp3＋Fargate 1 vCPU/2 GB ARM 每日 4 小時＋
   raw 歷史全量 ~10 GB Glacier IR）：大阪 ~US$50、Oregon ~US$34——
   **大阪貴約 47%（差 ~US$16/月）**；降到 t4g.micro 則為 ~US$31 vs ~US$22。
   記憶中的「便宜兩成餘」低估了 instance 部分（實為近四成）。
   費用面 Oregon 明確勝出，A3 風控無否決 → 定案。
2. **Fargate 出口 IP 的風控風險**：✅ A3 初驗通過（2026-08-28）——兩區 Fargate
   直連（無 proxy）probe 全 PASS，前提假設成立。每次 task 的 public IP 都不同
   （好事），但都落在 AWS 已公開的 IP 段，故風險未歸零：A4 並行期持續驗證，
   若正式期被擋，備案是掛 proxy（舊正式機模式，`settings.py` 已支援 rotating
   proxy middleware）——屆時費用另計，且正好餵 dx-roadmap 2.5-3 等待中的
   「真實被擋樣本」。
3. **Adminer 連線方式**：public IP + SG 白名單（簡單、有一瞬間暴露面）vs SSM port
   forwarding（零暴露、多裝 session-manager-plugin）。傾向 b，但用過再拍板。
4. **image 私有即可？** ECR private 是預設也是建議——image 內雖無機密，但 Dockerfile
   與依賴版本沒必要多一個公開面；公開的東西已經在 GitHub repo。
5. **舊 `devop/` 素材處置**：`devop.md` 內含歷史 DB 密碼與主機名，AWS 化落地後應清理
   （密碼輪替 + 檔案改寫），並把 `devop/aws/` 立為新的單一來源。
6. **舊 RDS 現況查證**：外部資訊已查明（t4g.micro／100 GB gp2／已用 85 GB，
   見〈AWS 實測補記〉）；raw 全在其中亦經 ddio 確認。**剩 in-DB 部分**（表級組成、
   raw 實際占比、與本機重疊段比對）**拍板延後**：不開 Publicly accessible，
   等 workbench task（A5）從 VPC 內網查。2026-08-26 曾嘗試公網連線：
   Public=Yes＋SG 放行皆就緒仍 timeout，subnet 疑為 private（route table 無 igw
   路由，唯讀權限無法確認）——反正不開了，此線索留給未來除錯參考。
7. **raw 保留窗口長度**：✅ 90 天定案（2026-08-28 查證）——(a) `invalidate` 走
   HouseTS 欄位穩定性、完全不讀 raw，日期範圍由操作者指定；(b) rerun 工具只能
   re-parse **現行 template**（舊版直接 `LegacyTemplateError`），實務回看深度＝
   parser bug 的發現延遲，遠短於 90 天；(c) 既有 archivehistory 預設 60 天已是
   驗證過的安全線。窗口改小隨時可以，改大要從 S3 撈包。
8. **現行這份 DB 的上雲路線**：✅ 已拍板（2026-08-28）——**重疊段以本機為準**
   （本機這份本來就是舊 RDS dump 的較新延續）。實作：遷移順序固定「先歷史段、
   後本機段」讓新資料自然蓋舊，並以 `ON CONFLICT … DO UPDATE … WHERE
   excluded.updated > existing.updated` 的 upsert guard 作第二層保證——
   正確性由資料時間戳決定，不依賴執行順序，任何批次重跑皆冪等。

---

## 編修紀錄

- **2026-08-28（三補）** A2 兩區 apply＋A3 兩區風控探測完成：**region 拍板
  us-west-2**（兩區 probe 全 PASS，風控無否決，按費用選；開放問題 1、2 結案）。
  執行紀要：terraform workspace oregon/osaka 分 state、IAM role 名稱帳號全域故
  第二區掛 `-osaka` 後綴（`name_suffix` 變數）；arm64 image 本機 qemu 跨平台
  build 後 push 兩區 ECR；probe 以 RunTask command override 跑，結果從
  CloudWatch logs＋exit code 收。大阪區資源待 destroy（含 ECR image 清空）。
- **2026-08-28（二補）** scoped profile `twrh` 就緒後的偵察第二輪：pricing API
  現價對比（開放問題 1 拍板依據 (a) 完成，費用面 Oregon 勝出）、annual-dump
  完整性抽驗；`twrhro` 憑證失效，RDS 側偵察三項待補。
- **2026-08-28** 實帳單比對校準費用結論（閒置資源已清理）；region 收斂為
  大阪 vs us-west-2 兩案、A3 兩區探測兼拍板；拍板重疊段以本機為準
  （先歷史段後本機段＋updated upsert guard，開放問題 8 結案）；annual-dump
  降級為對帳基準＋備援（歷史段改單趟讀舊 RDS 全欄位）；維持案 A 並補
  `raw_archived_at` 標記欄位；新增本機全套彩排計畫、遷移權限模式
  （最小 scope profile、破壞性操作永遠人工）、watchdog 零產出斷言的雲上對應。
- **2026-08-26（四補）** 補〈Fargate task 開多大〉（1 vCPU/2GB ARM64 起手＋量測計畫）
  與 RDS 寫入速率警語（本機數倍速塞完 vs 舊機長時攤平，gp3 IOPS 是關鍵）；
  排定 2026-08-27 00:10 全量（systemd-run 一次性 timer）附資源量測。
- **2026-08-26** 建立。盤點舊 EC2+crontab 模式與本機接手現況，拍板
  ECR + Fargate + EventBridge Scheduler + EFS + CloudWatch Logs 組合，
  費用估 ~US$7–10/月（RDS 外），列六階段與五個開放問題。
- **2026-08-26（三補）** AWS read-only 盤點（專用唯讀 IAM user）：
  查明舊 RDS 規格與剩餘空間、S3 兩 bucket 全貌，發現 `misc/annual-dump/` 歷史
  house_etc dump（無 raw）；據此修正 instance 建議（t4g.small 起跳）、migration
  步驟 4（歷史 detail_dict 直接取自 S3 dump）、開放問題 1/6/8。
- **2026-08-26（同日補）** 新增 RDS 費用節省與資料遷移兩節：實測現行 DB 54 GB 中
  raw HTML 佔 96%（+5 GB/月），拍板三槓桿（raw offload 到 S3 Glacier IR、
  HouseTS 90 天滾動窗口、t4g Single-AZ + 小 gp3）與「開新 instance 邊剝邊搬」的
  分批遷移流程；歷史總量以網站推估 8.84M 列。開放問題增至八個。
