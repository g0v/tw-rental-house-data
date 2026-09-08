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
3. 排程已預設開啟（A4 上線 2026-08-29；時間等 per-env 參數見 terraform.tfvars，
   不入版控）；要暫停用 `terraform apply -var enable_schedule=false`。

## 一次性指令與 D5／D6 切換 runbook（2026-09-05）

`run-cloud.sh <command...>`：用 crawler image 起一個 task 跑任意指令、等收工、印 log
（一次只起一個；要爬站的指令先 `-var enable_sweep_schedule=false` 暫停 sweep）。

| 步 | 指令 | 綠的判準 |
|---|---|---|
| 對帳補強（D5 前） | `run-cloud.sh poetry run python django/manage.py rawpack --reconcile-only --full --date 2026-09-04`（9/5 同） | `reconcile OK (full)`，mismatch 0；superseded＝之後重爬過、屬正常 |
| flow 雲上驗（D6a 前） | 日跑收工後 `run-cloud.sh poetry run python flow.py run --date <今天> --from rawpack` | `=== flow done`；manifest／日包重出、qualitycheck 綠 |
| D5 停寫＋D6a 切 flow | tfvars：`raw_db_write = "0"`、`crawler_command = ["poetry","run","python","flow.py","run"]` → `terraform apply` | 次日 02:10 `runcheck` 五項綠、rawpack 流程內成功（此時失敗＝硬紅） |
| D5 清空 | 綠後、避開爬蟲時段：`run-cloud.sh ./devop/rawcutover.sh`（dry-run）→ `--commit` | 包上 `raw/591/<YYYY-MM>*.tar.zst`，`house_etc` raw 欄位全 NULL；空間回收另 `VACUUM (FULL) house_etc`（可不做） |
| Phase 4 4a／4b 上線（9/9） | image 先出（model 已無 raw 欄）→ `rds-door.sh` 開門 `manage.py migrate`（0014 drop raw 欄、0006 drop stats）→ 關門；`terraform apply`（S3 policy 加 `list/*`、`parsed/*`、task def 加 `TWRH_ARTIFACT_DIR`、拿掉 `raw_db_write`）——apply 前 artifactpack 上傳會失敗但只 advisory、分區檔留在 EFS，apply 後補 `run-cloud.sh poetry run python django/manage.py artifactpack --tree list --date <日>`（parsed 同） | runcheck 看到 `=== list 591 <日> sweep-HHMM: … rows` 與 `uploaded s3://…/list/…`；隔日 `seedcheck: AGREE` |
| 1 日 export 補跑 | flow 若在 export 之後的 stage 紅，export 已出、不需補；若 export 本身紅：`run-cloud.sh poetry run python django/manage.py export -p`（task 的 TWRH_TARGET_DATE 未設時取真實當天，須在 1 日當天跑；否則加 `env TWRH_TARGET_DATE=YYYY-MM-01`）——**不要**用 `flow.py run --from export`，export 已是第一個 stage、會把整天重爬 | 07:00 publisher 前 `datas/` 有 `[YYYYMM][CSV][Raw]` zip |
| 回退 | tfvars 翻回 `raw_db_write = "1"` → apply（D6b 後 orchestrate.sh 已刪，排程只能指 flow；flow 出問題用 `--from` 續跑或 run-cloud 跑單一 manage 指令） | image 不需重出 |

## 刻意不做（見 aws-deployment-plan「刻意避開的費用陷阱」）

NAT Gateway（task 用 public subnet 直接出網）、常駐 EC2、K8s、Multi-AZ RDS。
