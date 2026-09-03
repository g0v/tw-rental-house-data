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

# 檔案 log 同步一份到 stdout → awslogs → CloudWatch，中途死也留有現場；
# tail -F 跨各 phase 的 mv/重建持續跟檔
tail -F scrapy.log 2>/dev/null &
TAIL_PID=$!

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
# L-C：TWRH_DETAIL_SEED_MODE=diff 啟用 skip 降頻（同 go.sh；拍板前預設 full）
SEED_MODE_FLAG=""
if [ "${TWRH_DETAIL_SEED_MODE:-full}" = "diff" ]; then
  SEED_MODE_FLAG="-a seed_mode=diff -a refresh_days=${TWRH_DETAIL_REFRESH_DAYS:-7}"
  echo "Detail seed mode: diff (refresh_days=${TWRH_DETAIL_REFRESH_DAYS:-7})"
fi
echo '===== SEED ====='
poetry run scrapy crawl detail591 -L INFO -a seed_only=True $SEED_MODE_FLAG
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
# 併入 worker 群的聚合速率觀察。
# 必須套 worker 的節流參數：primary 本身的 env 是 list 用的全速設定，直接拿來
# consume 會在幾分鐘內 403＋errback 斷餵、spider 靜默 finished（08-31 首航實踩，
# 423 resp/min 撐了 3.6 分鐘就陣亡）。---
echo '===== PRIMARY CONSUME ====='
BATCH="${DETAIL_BATCH_SIZE:-10000}"
# dx 4-2：batch 額滿由 spider touch marker 檔通知，不再 grep log 字串
MARKER=$(mktemp -u /tmp/twrh-batch-limit.XXXXXX)
n=1
while :; do
  rm -f "$MARKER"
  TWRH_CONCURRENT_REQUESTS="${TWRH_WORKER_CONCURRENCY:-1}" \
  TWRH_DOWNLOAD_DELAY="${TWRH_WORKER_DELAY:-1}" \
  poetry run scrapy crawl detail591 -L INFO -a consume_only=True -a batch_size="$BATCH" -a stop_marker="$MARKER"
  mv scrapy.log "../logs/$now.primary-detail.$n.log" 2>/dev/null || true
  [ -f "$MARKER" ] || break
  n=$((n+1))
done
rm -f "$MARKER"

# --- phase 3b: 輪詢 worker ARN 直到全 STOPPED 或逾時（exit 2）——queue 空後
# worker 隨即自然收工，這裡只是等尾巴；「worker 全停」仍是唯一可靠收尾閘門 ---
echo '===== WAIT FOR WORKERS ====='
timed_out=0
poetry run python devop/workers.py wait $ARNS || timed_out=1

# --- phase 4: 收尾。1-1 收工鐵律 seeds == terminals：worker 全停後 queue
# 必須全數終結（done+dead），殘留＝資料殘缺，當場紅、中止收尾——不讓
# sync/stats/export 把殘缺的一輪當正常資料處理；順帶滾動清理舊終結列 ---
echo '===== QUEUE FINALIZE ====='
if ! poetry run python ./django/manage.py queuefinalize; then
  echo '!!! queue finalize red (seeds != terminals) -- aborting before sync/stats/export'
  kill "$TAIL_PID" 2>/dev/null || true
  gzip ../logs/*.log 2>/dev/null || true
  poetry run python devop/workers.py ship_logs ../logs "$now" \
    || echo '!!! log shipping incomplete — leftovers stay on EFS'
  exit 1
fi

# L-C(8)：diff 模式下先補齊被 skip 物件的當日 TS，再讓 syncstateful 推導
if [ "${TWRH_DETAIL_SEED_MODE:-full}" = "diff" ]; then
  echo '===== SYNTHESIZE SKIPPED TS ====='
  poetry run python ./django/manage.py synthts
fi
echo '===== STATEFUL UPDATE ====='
poetry run python ./django/manage.py syncstateful -ts
echo '===== GENERATE STATISTICS ====='
poetry run python ./django/manage.py statscheck
echo '===== DISTRIBUTION CHECK ====='
poetry run python ./django/manage.py distcheck
# 1-2 新觀測通道（平行週；切換後退役 statscheck/distcheck/fill-rate/monthreport 舊讀法）
echo '===== MANIFEST + QUALITY CHECK ====='
poetry run python ./django/manage.py manifest
poetry run python ./django/manage.py qualitycheck
echo '===== CHECK EXPORT ====='
poetry run python ./django/manage.py export -p

echo '===== FINALIZE ====='
kill "$TAIL_PID" 2>/dev/null || true
gzip ../logs/*.log 2>/dev/null || true
# 本輪 log（含 worker 的，同 STAMP）歸檔 S3 logs/<date>/（lifecycle 30 天過期）
poetry run python devop/workers.py ship_logs ../logs "$now" \
  || echo '!!! log shipping incomplete — leftovers stay on EFS'
[ "$timed_out" = 1 ] && echo 'NOTE: finished with worker timeout — check data completeness'
echo '=== orchestrate done ==='
