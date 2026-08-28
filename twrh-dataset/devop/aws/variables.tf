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

variable "enable_rds" {
  description = "建新 RDS（rds.tf）。apply 前先人工把 /twrh/db-password 填真值"
  type        = bool
  default     = false
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
