#!/bin/bash

# Parse --append flag
APPEND_FLAG=""
if [[ "$1" == "--append" ]]; then
    APPEND_FLAG="-a append=True"
    echo "Running in APPEND mode"
fi

now=`date +'%Y.%m.%d.%H%M'`
mkdir -p ../logs

echo '===== LIST ====='
poetry run scrapy crawl list591 -L INFO $APPEND_FLAG
mv scrapy.log ../logs/$now.list.log

echo '===== DETAIL ====='
poetry run scrapy crawl detail591 -L INFO $APPEND_FLAG
mv scrapy.log ../logs/$now.detail.log

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
