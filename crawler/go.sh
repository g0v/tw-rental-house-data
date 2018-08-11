#!/bin/bash

now=`date +'%Y.%m.%d.%H%M'`
mkdir -p ../logs

. ../bin/activate
echo '===== LIST ====='
scrapy crawl list591 -L INFO
mv scrapy.log ../logs/$now.list.log
sleep 30

echo '===== DETAIL ====='
scrapy crawl detail591 -L INFO
mv scrapy.log ../logs/$now.detail.log

echo '===== STATEFUL UPDATE ====='
python ../backend/manage.py syncstateful -ts > ../logs/$now.stateful.log

echo '===== FINALIZE ====='
grep -n ERROR  ../logs/$now.*.log > ../logs/$now.error
gzip ../logs/*.log