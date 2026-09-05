variable "aws_profile" {
  description = "本機 AWS named profile（scoped 遷移用 user；CI 等無 profile 環境傳空字串）"
  type        = string
  default     = "twrh"
}

variable "region" {
  description = "部署 region（開放問題 1：ap-northeast-3 vs us-west-2，A3 拍板）"
  type        = string
}

variable "name_suffix" {
  description = "IAM role 名稱後綴（IAM 全域，A3 兩區並存期第二區要加，如 \"-osaka\"；拍板後正式區留空）"
  type        = string
  default     = ""
}

variable "enable_schedule" {
  description = "開啟每日爬蟲排程（A4 上線 2026-08-29；default true 讓日常 apply——如 rds-door.sh——不會不帶 var 就把排程砍掉）"
  type        = bool
  default     = true
}

variable "crawl_schedule" {
  description = "每日全量的 cron（Asia/Taipei，當日凌晨爬、TWRH_TARGET_DATE=當天）；實際時間 per-env 於 terraform.tfvars 設定"
  type        = string
  default     = "cron(0 4 * * ? *)"
}

# ---- primary（orchestrate.sh）的 list 階段速率 ----
variable "crawl_concurrency" {
  description = "primary list 階段 CONCURRENT_REQUESTS（per-env 於 terraform.tfvars 設定）"
  type        = string
  default     = "1"
}

variable "crawl_download_delay" {
  description = "primary list 階段 DOWNLOAD_DELAY 秒數（per-env 於 terraform.tfvars 設定）"
  type        = string
  default     = "1"
}

# ---- 2.5-3 detail worker 群：orchestrate.sh 用 run-task 開 N 個（各自新 IP）----
variable "detail_workers" {
  description = "consume-only detail worker 數（run-task --count）。0=orchestrate 只跑 list＋收尾不開 worker；per-env 於 terraform.tfvars 設定"
  type        = number
  default     = 0
}

variable "worker_concurrency" {
  description = "每個 worker 的 CONCURRENT_REQUESTS（1=純序列；per-env 於 terraform.tfvars 設定）"
  type        = string
  default     = "1"
}

variable "worker_download_delay" {
  description = "每個 worker 的 DOWNLOAD_DELAY 秒數（per-env 於 terraform.tfvars 設定）"
  type        = string
  default     = "1"
}

variable "worker_cpu" {
  description = "worker task cpu（run-task override，consume-only 較 primary 小）"
  type        = number
  default     = 256
}

variable "worker_memory" {
  description = "worker task memory（run-task override）"
  type        = number
  default     = 1024
}

variable "crawler_cpu" {
  type    = number
  default = 1024 # 1 vCPU——scrapy 單行程單執行緒，實測峰值約半顆核心
}

variable "crawler_memory" {
  type    = number
  default = 2048 # 實測 RSS 峰值 ~240 MB，2 GB 餘裕充足
}

variable "enable_rds" {
  description = "建新 RDS（rds.tf）。apply 前先人工把 /twrh/db-password 填真值"
  type        = bool
  default     = false
}

variable "rds_client_cidrs" {
  description = "允許直連 RDS 5432 的 CIDR（M2 workbench task／M3 開發機的當下 IP，遷移結束清空）"
  type        = list(string)
  default     = []
}

variable "rds_instance_class" {
  description = "t4g.small 起跳（M1 後判斷），micro 可一試（帳單見真章再調）"
  type        = string
  default     = "db.t4g.small"
}

variable "db_host" {
  description = "手動覆寫 DB endpoint；留空且 enable_rds=true 時自動接 rds.tf 的 endpoint"
  type        = string
  default     = ""
}

variable "db_name" {
  type    = string
  default = "twrh"
}

variable "db_user" {
  type    = string
  default = "twrh"
}

variable "detail_seed_mode" {
  description = "TWRH_DETAIL_SEED_MODE：full＝全量（現行）；diff＝L-C list-diff skip 降頻（dx-roadmap L-C，語意拍板後於 tfvars 切）"
  type        = string
  default     = "full"
}

variable "detail_refresh_days" {
  description = "TWRH_DETAIL_REFRESH_DAYS：diff 模式的週期強制刷新天數（L-C-7）"
  type        = string
  default     = "7"
}

variable "deal_lookback_days" {
  description = "TWRH_DEAL_LOOKBACK_DAYS：deals stage 回看天數（#229）。591 成交列表會在成交後數日持續補列，日跑取 7 保守（2026-09-05 拍板）"
  type        = string
  default     = "7"
}

variable "enable_publish_schedule" {
  description = "月度出貨排程（publisher 雲化，2026-09-05）：每月 1 日跑 publish.sh 出上個月。雲上 dry-run 驗過後於 tfvars 開"
  type        = bool
  default     = false
}

variable "publish_schedule" {
  description = "月度出貨 cron（Asia/Taipei）；須在 1 日的日爬（含月底 export -p）收工之後"
  type        = string
  default     = "cron(0 7 1 * ? *)"
}

variable "public_bucket" {
  description = "公開資料集 bucket（publish.sh 步驟 3 的上傳目標；ap-northeast-3）"
  type        = string
  default     = "twrh"
}

variable "publisher_cpu" {
  type    = number
  default = 1024
}

variable "publisher_memory" {
  type    = number
  default = 4096 # clickhouse local 聚合月 zip；2 GB 邊緣，給 4
}

variable "enable_sweep_schedule" {
  description = "前緣掃描排程（短命物件，2026-09-05）：白天每數小時掃 list 前緣＋新物件 detail。雲上 run-task 驗過後開"
  type        = bool
  default     = false
}

variable "sweep_schedule" {
  description = "前緣掃描 cron（Asia/Taipei）；須避開 02:00–05:00 日跑"
  type        = string
  default     = "cron(0 5,8,11,14,17,20,23 * * ? *)"
}

variable "housekeep_schedule" {
  description = "月度 housekeep（raw offload＋HouseTS 歸檔）的 cron（Asia/Taipei）；避開爬蟲時段"
  type        = string
  default     = "cron(0 12 3 * ? *)"
}

variable "robotstxt_obey" {
  description = "TWRH_ROBOTSTXT_OBEY（per-env 於 terraform.tfvars 設定）"
  type        = string
  default     = "1"
}

variable "autothrottle" {
  description = "TWRH_AUTOTHROTTLE（per-env 於 terraform.tfvars 設定）"
  type        = string
  default     = "1"
}
