#!/bin/bash

now=`date +'%Y.%m.%d.%H%M'`
mkdir -p ../logs

echo '===== LIST ====='
pipenv run scrapy crawl list591 -L INFO
mv scrapy.log ../logs/$now.list.log

echo '===== DETAIL ====='
pipenv run scrapy crawl detail591 -L INFO
mv scrapy.log ../logs/$now.detail.log

echo '===== STATEFUL UPDATE ====='
pipenv run python ../backend/manage.py syncstateful -ts

echo '===== CHECK EXPORT ====='
pipenv run python ../backend/manage.py export -p

echo '===== GENERATE STATISTICS ====='
pipenv run python ../backend/manage.py statscheck


echo '===== FINALIZE ====='
grep -n ERROR  ../logs/$now.*.log > ../logs/$now.error
gzip ../logs/*.log
