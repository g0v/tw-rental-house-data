variable "region" {
  description = "部署 region（開放問題 1：ap-northeast-3 vs us-west-2，A3 拍板）"
  type        = string
}

variable "enable_schedule" {
  description = "開啟每日爬蟲排程（A4 才轉 true；探測與遷移期間保持 false）"
  type        = bool
  default     = false
}

variable "crawl_schedule" {
  description = "每日全量的 cron（Asia/Taipei）"
  type        = string
  default     = "cron(3 20 * * ? *)"
}

variable "crawler_cpu" {
  type    = number
  default = 1024 # 1 vCPU——scrapy 單行程單執行緒，實測峰值約半顆核心
}

variable "crawler_memory" {
  type    = number
  default = 2048 # 實測 RSS 峰值 ~240 MB，2 GB 餘裕充足
}

variable "db_host" {
  description = "RDS endpoint（A2 建新 RDS 後填；RDS 本身另檔管理，尚未納入）"
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
