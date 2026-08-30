# A6：GitHub Actions build & push ECR（「push 即 deploy」閉環）。
# OIDC 免長期金鑰：GitHub 的 token 換 AWS 臨時憑證，trust 鎖定本 repo 的
# master branch。角色只能推兩個 ECR repo，無其他權限。
# schedule 拉 :latest，故 CI push 完成＝下一場 02:10 生效。

data "aws_caller_identity" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # GitHub 的 CA thumbprint；AWS 現已改用信任庫驗證，此值僅為 API 必填
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_role" "ci_ecr_push" {
  name = "twrh-ci-ecr-push${var.name_suffix}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:g0v/tw-rental-house-data:ref:refs/heads/master"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "ci_ecr_push" {
  name = "ecr-push"
  role = aws_iam_role.ci_ecr_push.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"]
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = [
          aws_ecr_repository.crawler.arn,
          aws_ecr_repository.publisher.arn,
        ]
      },
    ]
  })
}

output "ci_ecr_push_role_arn" {
  value = aws_iam_role.ci_ecr_push.arn
}
