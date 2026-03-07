#!/bin/bash

# Parse flags
APPEND_FLAG=""
START_EARLY_FLAG=""

while [[ $# -gt 0 ]]; do
    case $1 in
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
        *)
            echo "Unknown option: $1"
            shift
            ;;
    esac
done

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
