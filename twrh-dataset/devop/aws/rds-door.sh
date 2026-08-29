#!/bin/bash
# 新 RDS 白名單開關（開發機 IP 動態，用時開、用完關）：
#   ./rds-door.sh open            # 抓當下公網 IP，白名單 = [我的 /32]
#   ./rds-door.sh close           # 白名單清空（public endpoint 無人能進）
#   ./rds-door.sh open 1.2.3.4/32 # 額外保留其他 CIDR（如遷移期 workbench task）
# 爬蟲/workbench 走 task SG 規則，不受此白名單影響。
set -euo pipefail
cd "$(dirname "$0")"

MODE=${1:?usage: rds-door.sh open|close [extra_cidr ...]}; shift || true
EXTRA=("$@")

CIDRS=()
if [ "$MODE" = open ]; then
  ME=$(curl -s --max-time 10 https://checkip.amazonaws.com)
  CIDRS+=("$ME/32")
  echo "open for $ME/32"
elif [ "$MODE" != close ]; then
  echo "unknown mode: $MODE" >&2; exit 1
fi
CIDRS+=("${EXTRA[@]+"${EXTRA[@]}"}")

# close 模式下陣列為空：printf 零參數仍會印一輪空字串（[""]），要顯性給 []
if [ ${#CIDRS[@]} -eq 0 ]; then
  LIST="[]"
else
  LIST=$(printf '"%s",' "${CIDRS[@]}")
  LIST="[${LIST%,}]"
fi
terraform apply -auto-approve \
  -var region=us-west-2 -var enable_rds=true \
  -var "rds_client_cidrs=$LIST" | grep -E 'Apply complete|Error'
echo "rds_client_cidrs = $LIST"
