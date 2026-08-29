#!/bin/bash
# 雲上每日全量的編排器（docs/aws-deployment-plan 2.5-3 模型 A）。
# 取代 go.sh 在 Fargate 的角色（go.sh 留給本機單機跑）：
#   1. list591 inline 生種子（短、低併發）
#   2. run-task 開 N 個 consume-only detail worker（各自新公網 IP），握住 ARN
#   3. 輪詢這批 ARN 直到全 STOPPED 或逾 MAX_WAIT——「worker 全停」是唯一可靠的
#      收尾閘門（queue 空會有啟動瞬間假象＋硬殺孤兒認領，不可當閘門）
#   4. 收尾：syncstateful / statscheck / distcheck /（月底）export
# 逾時仍照常收尾但告警；list 熔斷則中止不開 worker。
set -uo pipefail
cd "$(dirname "$0")/.."   # -> /app/twrh-dataset

: "${TWRH_CLUSTER:?}" "${TWRH_TASK_DEF:?}" "${TWRH_SUBNETS:?}" "${TWRH_TASK_SG:?}"
REGION="${AWS_DEFAULT_REGION:-us-west-2}"
N="${TWRH_DETAIL_WORKERS:-1}"
WCPU="${TWRH_WORKER_CPU:-256}"
WMEM="${TWRH_WORKER_MEMORY:-1024}"
WCONC="${TWRH_WORKER_CONCURRENCY:-1}"
WDELAY="${TWRH_WORKER_DELAY:-1}"
BATCH="${DETAIL_BATCH_SIZE:-10000}"
MAX_WAIT="${TWRH_MAX_WAIT_SEC:-25200}"   # 收尾等待上限
export TWRH_TARGET_DATE="${TWRH_TARGET_DATE:-$(date +'%Y-%m-%d')}"
now=$(date +'%Y.%m.%d.%H%M')
mkdir -p ../logs
echo "=== orchestrate $TWRH_TARGET_DATE : $N workers, conc=$WCONC delay=$WDELAY ==="

breaker_tripped() { grep -q 'error_rate_exceeded' "$1"; }

# --- phase 1: list（本行程內跑）---
echo '===== LIST ====='
poetry run scrapy crawl list591 -L INFO
mv scrapy.log "../logs/$now.list.log"
if breaker_tripped "../logs/$now.list.log"; then
  echo '!!! list breaker tripped — abort, no workers launched'
  exit 1
fi

# --- phase 2: 開 N 個 consume-only worker，override cpu/mem/速率 ---
# worker command：batch 迴圈直到 queue 排空（consume_only 不生種子）
WORKER_CMD="n=1; while :; do poetry run scrapy crawl detail591 -L INFO -a consume_only=True -a batch_size=$BATCH; L=/data/logs/$now.worker-\$(hostname).\$n.log; mv scrapy.log \$L 2>/dev/null || true; grep -q 'Batch limit reached' \$L 2>/dev/null || break; n=\$((n+1)); done"
OVERRIDES=$(cat <<JSON
{"cpu":"$WCPU","memory":"$WMEM","containerOverrides":[{"name":"crawler",
"cpu":$WCPU,"memory":$WMEM,
"command":["bash","-c","$WORKER_CMD"],
"environment":[{"name":"TWRH_TARGET_DATE","value":"$TWRH_TARGET_DATE"},
{"name":"TWRH_CONCURRENT_REQUESTS","value":"$WCONC"},
{"name":"TWRH_DOWNLOAD_DELAY","value":"$WDELAY"}]}]}
JSON
)
NETCFG="awsvpcConfiguration={subnets=[$TWRH_SUBNETS],securityGroups=[$TWRH_TASK_SG],assignPublicIp=ENABLED}"

echo "===== LAUNCH $N WORKERS ====="
ARNS=$(aws ecs run-task --region "$REGION" --cluster "$TWRH_CLUSTER" \
  --task-definition "$TWRH_TASK_DEF" --launch-type FARGATE --count "$N" \
  --network-configuration "$NETCFG" --overrides "$OVERRIDES" \
  --started-by "orchestrate-$now" \
  --query 'tasks[].taskArn' --output text)
if [ -z "$ARNS" ]; then
  echo '!!! run-task returned no ARNs — abort before finalize'
  exit 1
fi
echo "workers: $ARNS"

# --- phase 3: 輪詢 worker ARN 直到全 STOPPED 或逾時 ---
echo '===== WAIT FOR WORKERS ====='
start=$(date +%s)
timed_out=0
while :; do
  running=$(aws ecs describe-tasks --region "$REGION" --cluster "$TWRH_CLUSTER" \
    --tasks $ARNS --query 'length(tasks[?lastStatus!=`STOPPED`])' --output text 2>/dev/null || echo ERR)
  [ "$running" = "0" ] && { echo 'all workers STOPPED'; break; }
  if [ $(( $(date +%s) - start )) -ge "$MAX_WAIT" ]; then
    echo "!!! MAX_WAIT reached, $running worker(s) still not STOPPED — finalize anyway"
    timed_out=1; break
  fi
  echo "  waiting: $running worker(s) still running ($(( ($(date +%s)-start)/60 ))m)"
  sleep 120
done

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
