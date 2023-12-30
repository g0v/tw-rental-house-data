#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR
mkdir -p ../logs

setsid ./go.sh >> ../logs/`date +'%Y.%m.%d.%H%M'`.go.log 2>&1 &
