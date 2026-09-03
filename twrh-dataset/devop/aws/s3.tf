# raw bucket（us-west-2，命名沿用 twrh-w1 的區域後綴慣例）：
# - raw/<vendor>/<YYYY-MM>.tar.zst：3-1 界線日前的 housekeep 月包（拍板：不回整，
#   維持原格式、僅 debug 價值）＋同名 index json
# - raw/<vendor>/<YYYY-MM-DD>.tar.zst＋.index.jsonl：3-1 起 rawpack 的日包
#   （方案 A：finalize 單包；versioning 不開，重寫即覆蓋）
# - archive/：archivehistory tar／EFS 長期封存——無 expiration、刪除永遠人工
# - logs/<date>/*.gz：orchestrate finalize 歸檔的完整爬取 log（ship_logs）
# lifecycle（set-once，非排程 job；2026-09-03 拍板）：
#   raw/ 30 天轉 Glacier IR、365 天過期——個資／著作權暴露面從永存變有界；
#   更早歷史以 normalized 分區＋公開 zip 為準。logs/ 30 天過期（2026-08-31 拍板）。
# DeleteObject 仍不授予任何角色（lifecycle 過期不需要它）。

resource "aws_s3_bucket" "raw" {
  bucket = "twrh-w2"
}

resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    id     = "expire-logs-30d"
    status = "Enabled"
    filter {
      prefix = "logs/"
    }
    expiration {
      days = 30
    }
  }
  rule {
    id     = "raw-glacier-ir-30d-expire-365d"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    transition {
      days          = 30
      storage_class = "GLACIER_IR"
    }
    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# crawler task role（workbench／排程任務共用）：raw prefix 讀寫，無刪除
resource "aws_iam_role_policy" "crawler_raw_upload" {
  name = "raw-offload-upload"
  role = aws_iam_role.crawler_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = [
          "${aws_s3_bucket.raw.arn}/raw/*",
          # housekeep.sh 的 HouseTS 歸檔（archivehistory tgz）
          "${aws_s3_bucket.raw.arn}/archive/*",
          # orchestrate finalize 的爬取 log 歸檔（ship_logs，30 天 lifecycle）
          "${aws_s3_bucket.raw.arn}/logs/*",
          # 1-2 觀測層 manifest（manifest command 日日上傳，重跑覆蓋）
          "${aws_s3_bucket.raw.arn}/manifests/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.raw.arn]
      },
      # M2 fallback：annual-dump 由 workbench 直載（本機跑受限家用上行頻寬）
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["arn:aws:s3:::twrh/misc/annual-dump/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::twrh"]
      },
    ]
  })
}

output "raw_bucket" {
  value = aws_s3_bucket.raw.bucket
}
