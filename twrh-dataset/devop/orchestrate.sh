#!/bin/bash
# 雲上每日全量的編排器（docs/aws-deployment-plan 2.5-3 模型 A）。
# 取代 go.sh 在 Fargate 的角色（go.sh 留給本機單機跑）：
#   1. list591 inline（短、低併發）
#   1.5 detail591 seed_only 生 detail 種子（worker 都 consume_only，不會生）
#   2. run-task 開 N 個 consume-only detail worker（各自新公網 IP），握住 ARN
#   3a. primary 也跑 consume_only batch 迴圈到 queue 排空（等待期不閒置）
#   3b. 輪詢 worker ARN 直到全 STOPPED 或逾 MAX_WAIT——「worker 全停」是唯一可靠的
#      收尾閘門（queue 空會有啟動瞬間假象＋硬殺孤兒認領，不可當閘門）
#   4. 收尾：syncstateful / statscheck / distcheck /（月底）export
# 逾時仍照常收尾但告警；list 熔斷則中止不開 worker。
set -uo pipefail
cd "$(dirname "$0")/.."   # -> /app/twrh-dataset

: "${TWRH_CLUSTER:?}" "${TWRH_TASK_DEF:?}" "${TWRH_SUBNETS:?}" "${TWRH_TASK_SG:?}"
N="${TWRH_DETAIL_WORKERS:-1}"
export TWRH_TARGET_DATE="${TWRH_TARGET_DATE:-$(date +'%Y-%m-%d')}"
export TWRH_LOG_STAMP="$(date +'%Y.%m.%d.%H%M')"
now="$TWRH_LOG_STAMP"
mkdir -p ../logs
echo "=== orchestrate $TWRH_TARGET_DATE : $N workers ==="

breaker_tripped() { grep -q 'error_rate_exceeded' "$1"; }

# --- phase 1: list（本行程內跑）---
echo '===== LIST ====='
poetry run scrapy crawl list591 -L INFO
mv scrapy.log "../logs/$now.list.log"
if breaker_tripped "../logs/$now.list.log"; then
  echo '!!! list breaker tripped — abort, no workers launched'
  exit 1
fi

# --- phase 1.5: 生 detail 種子——consume-only worker 不生種子，種子由 primary
# 在這裡生（首航 2026-08-30 實測：漏了這步，worker 全數 0 items 秒退）---
echo '===== SEED ====='
poetry run scrapy crawl detail591 -L INFO -a seed_only=True
mv scrapy.log "../logs/$now.seed.log"
if ! grep -q 'seed-only mode' "../logs/$now.seed.log"; then
  echo '!!! seed generation failed — abort, no workers launched'
  exit 1
fi

# --- phase 2: 開 N 個 consume-only worker（boto3 helper，免裝 aws CLI）---
echo "===== LAUNCH $N WORKERS ====="
ARNS=$(poetry run python devop/workers.py launch)
if [ -z "$ARNS" ]; then
  echo '!!! run-task returned no ARNs — abort before finalize'
  exit 1
fi
echo "workers: $ARNS"

# --- phase 3a: primary 也當 consumer——等待期純 poll 是浪費（1 vCPU 閒數小時），
# 改跑與 worker 相同的 consume_only batch 迴圈直到 queue 排空。多的這個出口 IP
# 併入 worker 群的聚合速率觀察。---
echo '===== PRIMARY CONSUME ====='
BATCH="${DETAIL_BATCH_SIZE:-10000}"
n=1
while :; do
  poetry run scrapy crawl detail591 -L INFO -a consume_only=True -a batch_size="$BATCH"
  mv scrapy.log "../logs/$now.primary-detail.$n.log" 2>/dev/null || true
  grep -q 'Batch limit reached' "../logs/$now.primary-detail.$n.log" 2>/dev/null || break
  n=$((n+1))
done

# --- phase 3b: 輪詢 worker ARN 直到全 STOPPED 或逾時（exit 2）——queue 空後
# worker 隨即自然收工，這裡只是等尾巴；「worker 全停」仍是唯一可靠收尾閘門 ---
echo '===== WAIT FOR WORKERS ====='
timed_out=0
poetry run python devop/workers.py wait $ARNS || timed_out=1

# --- phase 4: 收尾（worker 全停後，殘留 request_ts = 失敗，statscheck 會報）---
echo '===== STATEFUL UPDATE ====='
poetry run python ./django/manage.py syncstateful -ts
echo '===== GENERATE STATISTICS ====='
poetry run python ./django/manage.py statscheck
echo '===== DISTRIBUTION CHECK ====='
poetry run python ./django/manage.py distcheck
echo '===== CHECK EXPORT ====='
poetry run python ./django/manage.py export -p

echo '===== FINALIZE ====='
gzip ../logs/*.log 2>/dev/null || true
[ "$timed_out" = 1 ] && echo 'NOTE: finished with worker timeout — check data completeness'
echo '=== orchestrate done ==='
