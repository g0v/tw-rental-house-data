# raw bucket（us-west-2，命名沿用 twrh-w1 的區域後綴慣例）：
# - raw/<vendor>/<YYYY-MM>.tar.zst（Glacier IR，上傳端指定 storage class）＋同名 index json
# - 之後 archivehistory tar／EFS 長期封存也收這裡
# 刻意不設 lifecycle expiration、不給任何角色 DeleteObject——刪除永遠人工。

resource "aws_s3_bucket" "raw" {
  bucket = "twrh-w2"
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
        Resource = ["${aws_s3_bucket.raw.arn}/raw/*"]
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
