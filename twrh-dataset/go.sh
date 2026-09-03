#!/bin/bash

usage() {
    cat <<'USAGE'
Usage: ./go.sh [OPTIONS]

Run the full crawl pipeline: list -> detail -> sync -> stats -> export.

Options:
  --append        Append mode: crawl new listings without clearing existing data
  --start-early   Start-early mode: when run after 22:00, use tomorrow's date
                  (ignored when --date is specified)
  --date DATE     Pin the target date (YYYY-MM-DD) for the entire pipeline run.
                  Default: today's date when go.sh starts.
  -h, --help      Show this help message and exit

Examples:
  ./go.sh                          # Normal run, pinned to today
  ./go.sh --append                 # Append mode
  ./go.sh --date 2026-03-20        # Re-run pipeline for a specific date
  ./go.sh --append --start-early   # Append + start-early mode
USAGE
    exit 0
}

# Parse flags
APPEND_FLAG=""
START_EARLY_FLAG=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            ;;
        --append)
            APPEND_FLAG="-a append=True"
            echo "Running in APPEND mode"
            shift
            ;;
        --start-early)
            START_EARLY_FLAG="-a start_early=True"
            echo "Running in START-EARLY mode"
            shift
            ;;
        --date)
            export TWRH_TARGET_DATE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            shift
            ;;
    esac
done

# Pin target date to when go.sh starts, unless overridden by --date
export TWRH_TARGET_DATE="${TWRH_TARGET_DATE:-$(date +'%Y-%m-%d')}"
echo "Running with TARGET DATE: $TWRH_TARGET_DATE"

# 熔斷（ErrorRateBreaker）觸發時中止 pipeline，不讓 sync/stats/export
# 把殘缺的一輪當正常資料處理（dx-roadmap 4-2 的最小前哨）
abort_if_breaker_tripped() {
    if grep -q 'error_rate_exceeded' "$1"; then
        echo "!!! Breaker tripped (error_rate_exceeded), see $1 -- aborting pipeline"
        exit 1
    fi
}

now=`date +'%Y.%m.%d.%H%M'`
mkdir -p ../logs

echo '===== LIST ====='
poetry run scrapy crawl list591 -L INFO $APPEND_FLAG $START_EARLY_FLAG
mv scrapy.log ../logs/$now.list.log
abort_if_breaker_tripped ../logs/$now.list.log

echo '===== DETAIL ====='
DETAIL_BATCH=1
# 2000 是 playwright/OCR 時代的 memory-leak 保險；兩者已移除（dx 4-5），
# 可用環境變數放大實測（見 docs/aws-deployment-plan.md 的 sizing 量測）
DETAIL_BATCH_SIZE=${DETAIL_BATCH_SIZE:-2000}
# L-C：TWRH_DETAIL_SEED_MODE=diff 啟用 list diff 驅動的 skip 降頻
# （dx-roadmap L-C；發布語意見 L-C-8，拍板前預設 full＝現行全量）。
# .env 只有 scrapy 行程會讀（dotenv），這裡的 shell 判斷要自己補讀
if [ -z "${TWRH_DETAIL_SEED_MODE:-}" ] && [ -f .env ]; then
    TWRH_DETAIL_SEED_MODE=$(grep -E '^TWRH_DETAIL_SEED_MODE=' .env | tail -1 | cut -d= -f2)
    TWRH_DETAIL_REFRESH_DAYS=$(grep -E '^TWRH_DETAIL_REFRESH_DAYS=' .env | tail -1 | cut -d= -f2)
fi
DETAIL_SEED_MODE=${TWRH_DETAIL_SEED_MODE:-full}
SEED_MODE_FLAG=""
if [ "$DETAIL_SEED_MODE" = "diff" ]; then
    SEED_MODE_FLAG="-a seed_mode=diff -a refresh_days=${TWRH_DETAIL_REFRESH_DAYS:-7}"
    echo "Detail seed mode: diff (refresh_days=${TWRH_DETAIL_REFRESH_DAYS:-7})"
fi
# dx 4-2：batch 額滿由 spider touch marker 檔（-a stop_marker）通知，
# 不再 grep log 字串當控制流（改一句訊息就壞）
BATCH_MARKER=$(mktemp -u /tmp/twrh-batch-limit.XXXXXX)
while true; do
    echo "--- detail batch $DETAIL_BATCH ---"
    rm -f "$BATCH_MARKER"
    poetry run scrapy crawl detail591 -L INFO $APPEND_FLAG $START_EARLY_FLAG $SEED_MODE_FLAG -a batch_size=$DETAIL_BATCH_SIZE -a stop_marker=$BATCH_MARKER
    mv scrapy.log ../logs/$now.detail.$DETAIL_BATCH.log
    abort_if_breaker_tripped ../logs/$now.detail.$DETAIL_BATCH.log
    # Exit loop when spider finishes before hitting the batch limit (all done)
    if [ ! -f "$BATCH_MARKER" ]; then
        break
    fi
    DETAIL_BATCH=$((DETAIL_BATCH + 1))
done
rm -f "$BATCH_MARKER"

# 1-1 收工鐵律：seeds == terminals（done+dead==seeds、無殘留）。
# 紅＝資料殘缺（403 全滅、seed 零產出、spider 假 finished），當場中止，
# 不讓 sync/stats/export 把殘缺的一輪當正常資料處理；順帶滾動清理舊終結列
echo '===== QUEUE FINALIZE ====='
if ! poetry run python ./django/manage.py queuefinalize; then
    echo "!!! queue finalize red (seeds != terminals) -- aborting pipeline"
    exit 1
fi

# L-C(8)：diff 模式下補齊被 skip 物件的當日 HouseTS（合成快照，標
# is_synthesized），要在 syncstateful 之前——它吃當日 TS 推導成交狀態
if [ "$DETAIL_SEED_MODE" = "diff" ]; then
    echo '===== SYNTHESIZE SKIPPED TS ====='
    poetry run python ./django/manage.py synthts
fi

echo '===== STATEFUL UPDATE ====='
poetry run python ./django/manage.py syncstateful -ts

echo '===== GENERATE STATISTICS ====='
poetry run python ./django/manage.py statscheck

# 「值對不對」防線：當日分佈不變量 vs baselines/national.json（591 資料混淆哨兵）。
# 只告警不擋 export——資料已入庫，出不出貨是月度 gate 的事
echo '===== DISTRIBUTION CHECK ====='
poetry run python ./django/manage.py distcheck

# do this in last step, as it may run for a long time
echo '===== CHECK EXPORT ====='
poetry run python ./django/manage.py export -p

echo '===== FINALIZE ====='
grep -nE 'ERROR|CRITICAL' ../logs/$now.*.log > ../logs/$now.error
gzip ../logs/*.log
