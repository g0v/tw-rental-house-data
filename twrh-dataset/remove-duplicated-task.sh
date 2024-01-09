#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR

now=`date +'%Y.%m.%d.%H%M'`
echo "------ $now ------" >> ../logs/deduprequest.log
poetry run python ./django/manage.py deduprequest >> ../logs/deduprequest.log
