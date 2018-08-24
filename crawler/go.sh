#!/bin/bash

now=`date +'%Y.%m.%d.%H%M'`
mkdir -p ../logs

. ../bin/activate
echo '===== LIST ====='
scrapy crawl list591 -L INFO
mv scrapy.log ../logs/$now.list.log

echo '===== DETAIL ====='
scrapy crawl detail591 -L INFO
mv scrapy.log ../logs/$now.detail.log

echo '===== STATEFUL UPDATE ====='
python ../backend/manage.py syncstateful -ts

echo '===== CHECK EXPORT ====='
python ../backend/manage.py export -p

echo '===== GENERATE STATISTICS ====='
python ../backend/manage.py statscheck


echo '===== FINALIZE ====='
grep -n ERROR  ../logs/$now.*.log > ../logs/$now.error
gzip ../logs/*.log
