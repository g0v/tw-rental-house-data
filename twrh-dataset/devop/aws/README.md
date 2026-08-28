# devop/aws — ECS Fargate 部署（docs/aws-deployment-plan.md A2）

> region ✅ 拍板 **us-west-2**（2026-08-28，A3 兩區 probe 全 PASS 後按費用選）。
> state 用 terraform workspace：`oregon`（正式，IAM role 正式名）；`osaka` 為
> A3 探測遺留，destroy 後移除。IAM role 名稱帳號全域，兩區並存要 `-var
> name_suffix=-<region>` 錯開。

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
   **填完 db-password 才可開 RDS**：`terraform apply -var region=us-west-2
   -var enable_rds=true`（rds.tf；master 密碼建立時讀該參數一次，之後輪替
   人工、terraform 不追；deletion_protection 常開）。
2. Push image：`docker build --target crawler -t <ecr>/twrh-crawler .`（repo 根目錄
   Dockerfile；正式由 GitHub Actions 做，A6）。
3. 開排程：`terraform apply -var enable_schedule=true`（A4，與本機並行驗證後）。

## 刻意不做（見 aws-deployment-plan「刻意避開的費用陷阱」）

NAT Gateway（task 用 public subnet 直接出網）、常駐 EC2、K8s、Multi-AZ RDS。
