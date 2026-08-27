# devop/aws — ECS Fargate 部署（docs/aws-deployment-plan.md A2）

> 草稿 skeleton（2026-08-28，零權限期先寫好備 apply）。region 未拍板（大阪 vs
> us-west-2，等 A3 兩區探測），以 `var.region` 參數化。

## 內容

- `variables.tf` / `main.tf` / `iam.tf` — ECR ×2、ECS cluster、CloudWatch Logs
  （90 天保留）、EFS（IA lifecycle）、crawler/publisher task definitions
  （1 vCPU / 2 GB ARM64）、EventBridge Scheduler（預設關閉，A4 才開）。
- `policies/migrate-dev-profile.json` — 開發機遷移用 IAM user 的最小權限
  policy（人工建 user 時貼上；**不含任何刪除／停機權限**，破壞性操作永遠人工）。

## 用法

```bash
cd twrh-dataset/devop/aws
terraform init
terraform plan  -var region=ap-northeast-3   # 或 us-west-2
terraform apply -var region=ap-northeast-3
```

Apply 後仍需人工做的事：

1. SSM SecureString 填值（terraform 只建佔位）：
   `/twrh/db-password`、`/twrh/slack-webhook`、`/twrh/sentry-dsn`。
2. Push image：`docker build --target crawler -t <ecr>/twrh-crawler .`（repo 根目錄
   Dockerfile；正式由 GitHub Actions 做，A6）。
3. 開排程：`terraform apply -var enable_schedule=true`（A4，與本機並行驗證後）。

## 刻意不做（見 aws-deployment-plan「刻意避開的費用陷阱」）

NAT Gateway（task 用 public subnet 直接出網）、常駐 EC2、K8s、Multi-AZ RDS。
