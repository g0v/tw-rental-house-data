#!/bin/bash
# RDS snapshot → S3 Parquet（見 rds-export.tf）。人工觸發、每次一個 export id、永不覆蓋。
#   devop/aws/rds-export.sh <snapshot-id> [table ...]     # 預設 house_etc house；table 寫 public.<name>
#   devop/aws/rds-export.sh status <export-id>
#   devop/aws/rds-export.sh list
# snapshot-id：自動快照形如 rds:twrh-2026-09-13-08-32（describe-db-snapshots 可查），手動快照給自己的名字。
# 匯出時間與 snapshot 大小成正比（100 GiB 級約 1–2 小時）；費用 $0.01/GB（snapshot 大小）＋S3。
set -euo pipefail
PROFILE=${TWRH_AWS_PROFILE:-twrh}; REGION=${AWS_DEFAULT_REGION:-us-west-2}
AWS=(aws --profile "$PROFILE" --region "$REGION")
HERE=$(cd "$(dirname "$0")" && pwd)
BUCKET=twrh-w2; DB=twrh

[ $# -gt 0 ] || { sed -n 2,8p "$0"; exit 2; }

case "$1" in
  status)
    "${AWS[@]}" rds describe-export-tasks --export-task-identifier "$2" \
      --query 'ExportTasks[0].{status:Status,percent:PercentProgress,total_gb:TotalExtractedDataInGB,started:TaskStartTime,ended:TaskEndTime,failure:FailureCause,warning:WarningMessage}' --output json
    exit 0 ;;
  list)
    "${AWS[@]}" rds describe-export-tasks --query 'ExportTasks[].[ExportTaskIdentifier,Status,PercentProgress,S3Prefix]' --output text
    exit 0 ;;
esac

SNAP=$1; shift
TABLES=("$@"); [ ${#TABLES[@]} -gt 0 ] || TABLES=(house_etc house)
ONLY=(); for t in "${TABLES[@]}"; do ONLY+=("$DB.public.$t"); done

ROLE=$(terraform -chdir="$HERE" output -raw rds_export_role_arn)
KEY=$(terraform -chdir="$HERE" output -raw rds_export_kms_key_arn)
ARN=$("${AWS[@]}" rds describe-db-snapshots --db-snapshot-identifier "$SNAP" --query 'DBSnapshots[0].DBSnapshotArn' --output text)
[ -n "$ARN" ] && [ "$ARN" != "None" ] || { echo "!!! snapshot $SNAP not found"; exit 1; }
ID="twrh-export-$(echo "$SNAP" | tr -c 'a-z0-9-\n' '-' | sed 's/^-*//; s/-*$//')-$(date +%Y%m%d%H%M)"

echo "export $ID: $ARN → s3://$BUCKET/archive/rds/$ID/ tables: ${ONLY[*]}"
"${AWS[@]}" rds start-export-task --export-task-identifier "$ID" --source-arn "$ARN" \
  --s3-bucket-name "$BUCKET" --s3-prefix "archive/rds" --iam-role-arn "$ROLE" --kms-key-id "$KEY" \
  --export-only "${ONLY[@]}" --query '{id:ExportTaskIdentifier,status:Status}' --output json
echo "進度：$0 status $ID"
