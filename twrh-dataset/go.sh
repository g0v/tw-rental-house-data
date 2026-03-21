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

now=`date +'%Y.%m.%d.%H%M'`
mkdir -p ../logs

echo '===== LIST ====='
poetry run scrapy crawl list591 -L INFO $APPEND_FLAG $START_EARLY_FLAG
mv scrapy.log ../logs/$now.list.log

echo '===== DETAIL ====='
DETAIL_BATCH=1
DETAIL_BATCH_SIZE=2000
while true; do
    echo "--- detail batch $DETAIL_BATCH ---"
    poetry run scrapy crawl detail591 -L INFO $APPEND_FLAG $START_EARLY_FLAG -a batch_size=$DETAIL_BATCH_SIZE
    mv scrapy.log ../logs/$now.detail.$DETAIL_BATCH.log
    # Exit loop when spider finishes before hitting the batch limit (all done)
    if ! grep -q 'Batch limit reached' ../logs/$now.detail.$DETAIL_BATCH.log; then
        break
    fi
    DETAIL_BATCH=$((DETAIL_BATCH + 1))
done

echo '===== STATEFUL UPDATE ====='
poetry run python ./django/manage.py syncstateful -ts

echo '===== GENERATE STATISTICS ====='
poetry run python ./django/manage.py statscheck

# do this in last step, as it may run for a long time
echo '===== CHECK EXPORT ====='
poetry run python ./django/manage.py export -p

echo '===== FINALIZE ====='
grep -n ERROR  ../logs/$now.*.log > ../logs/$now.error
gzip ../logs/*.log
