#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR
mkdir -p ../logs

# Pass through all arguments (--append, --start-early, etc.)
setsid ./go.sh "$@" >> ../logs/`date +'%Y.%m.%d.%H%M'`.go.log 2>&1 &
