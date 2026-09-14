# RDS snapshot → S3 Parquet 匯出（2026-09-14 拍板：photoids 走「export snapshot to S3」；
# 同一條路也是 S2 drop house_etc 前的歷史歸檔——2018–2023 的 detail_dict 只存在 DB，
# raw 月包沒有那些年，parser 也早已換版式，匯出成 Parquet 後不需要任何 DB 就讀得到）。
#
# 只建兩樣靜態資源：export 服務用的 IAM role（只能寫 archive/rds/*）與 customer-managed
# KMS key（AWS 硬性要求）。實際匯出由 devop/aws/rds-export.sh 起 start-export-task，
# 每次人工觸發、每次一個 prefix（archive/rds/<export-id>/），永不覆蓋。
#
#   terraform apply                              # 建 role＋key（一次）
#   ./rds-export.sh rds:twrh-2026-09-13-08-32    # 匯 house_etc＋house（預設）
#   ./rds-export.sh status twrh-export-…         # 看進度
#
# 產物：s3://twrh-w2/archive/rds/<export-id>/twrh/twrh.public.house_etc/…/*.parquet
#（AWS 匯出的目錄結構＝<export-id>/<db>/<db>.<schema>.<table>/<n>/part-*.parquet；
# detail_dict 這類 jsonb 欄在 Parquet 裡是 string）。刪除永遠人工（archive/ 無 lifecycle）。

resource "aws_kms_key" "rds_export" {
  description             = "twrh RDS snapshot export to S3 (archive/rds/*)"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "rds_export" {
  name          = "alias/twrh-rds-export"
  target_key_id = aws_kms_key.rds_export.key_id
}

resource "aws_iam_role" "rds_export" {
  name = "twrh-rds-export"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "export.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# AWS 文件列出的最小集合；限定 archive/rds/ prefix，不碰 raw／parsed／snapshot
resource "aws_iam_role_policy" "rds_export_s3" {
  name = "rds-export-archive"
  role = aws_iam_role.rds_export.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.raw.arn]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject*", "s3:GetObject*", "s3:DeleteObject*",
        ]
        Resource = ["${aws_s3_bucket.raw.arn}/archive/rds/*"]
      },
    ]
  })
}

# 匯出物件是這把 key 的 SSE-KMS 加密：crawler task（run-cloud 跑 tools/photo_ids_from_export.py 等
# 讀 archive/rds/ 的分析工具）要能 Decrypt；只限這一把 key
resource "aws_iam_role_policy" "crawler_rds_export_read" {
  name = "rds-export-kms-read"
  role = aws_iam_role.crawler_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kms:Decrypt", "kms:DescribeKey"]
      Resource = [aws_kms_key.rds_export.arn]
    }]
  })
}

output "rds_export_role_arn" {
  value = aws_iam_role.rds_export.arn
}

output "rds_export_kms_key_arn" {
  value = aws_kms_key.rds_export.arn
}
