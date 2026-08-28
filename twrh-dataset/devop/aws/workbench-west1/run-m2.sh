#!/bin/bash
# M2 歷史段遷移：workbench task（us-west-1）→ 新 RDS（us-west-2，公網＋SG 白名單）。
# 用法：./run-m2.sh <new-rds-endpoint> [額外 migrate 參數...]
#   1. RunTask（command override：等 SG 白名單放行 → copy_tables → strip_house_etc → verify_counts）
#   2. 印出 task 的 public IP——拿去 rds_client_cidrs apply，task 的等待迴圈就會通
#   3. 進度看 CloudWatch /twrh/workbench
set -euo pipefail
ENDPOINT=$1; shift || true
PROFILE=twrh
REGION=us-west-1
CLUSTER=twrh-workbench

DSN="postgresql://twrh@${ENDPOINT}:5432/twrh?sslmode=require"
S3_PREFIX="s3://twrh-w2/raw/591"

# 等新 RDS 放行（白名單 apply 需要 task 先起來拿到 IP），最多 30 分鐘
CMD="until pg_isready -h ${ENDPOINT} -p 5432 -t 5; do echo waiting-for-sg-allowlist; sleep 30; done
python tools/migrate/copy_tables.py
python tools/migrate/strip_house_etc.py
python tools/migrate/verify_counts.py"

TASK_ARN=$(aws ecs run-task --profile $PROFILE --region $REGION \
  --cluster $CLUSTER --launch-type FARGATE --task-definition twrh-workbench \
  --network-configuration 'awsvpcConfiguration={subnets=[subnet-07549db037dbf8cbb],securityGroups=[sg-01c13576fe0ba7233,sg-01d6ffe5b75143384],assignPublicIp=ENABLED}' \
  --overrides "$(python3 - "$DSN" "$S3_PREFIX" "$CMD" <<'PY'
import json, sys
dsn, s3, cmd = sys.argv[1:4]
print(json.dumps({"containerOverrides": [{
    "name": "workbench",
    "command": ["bash", "-lc", cmd],
    "environment": [
        {"name": "TWRH_MIGRATE_TARGET_DSN", "value": dsn},
        {"name": "TWRH_MIGRATE_S3_PREFIX", "value": s3},
    ],
}]}))
PY
)" --query 'tasks[0].taskArn' --output text)
echo "task: $TASK_ARN"

echo -n "waiting for ENI"
for _ in $(seq 30); do
  ENI=$(aws ecs describe-tasks --profile $PROFILE --region $REGION --cluster $CLUSTER --tasks "$TASK_ARN" \
    --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text)
  [ -n "$ENI" ] && [ "$ENI" != "None" ] && break
  echo -n .; sleep 5
done
IP=$(aws ec2 describe-network-interfaces --profile $PROFILE --region $REGION \
  --network-interface-ids "$ENI" --query 'NetworkInterfaces[0].Association.PublicIp' --output text)
echo
echo "workbench public IP: $IP"
echo "→ 白名單放行：terraform -chdir=../ apply -var region=us-west-2 -var enable_rds=true \\"
echo "    -var 'rds_client_cidrs=[\"<dev-ip>/32\",\"$IP/32\"]'"
